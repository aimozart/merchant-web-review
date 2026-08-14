"""
Tier 2 fault-injection registry: the Docker Compose / service layer.

Unlike ops/faults.py (Tier 1 — pure Django model/data mutations), these faults
manipulate the *actual running containers* backing this project's local stack
(docker-compose.yml) via the Docker SDK, and their `check_resolved` functions do
real connectivity checks against the real service — not just "is the container
object marked running," but "can something actually talk to it." This is meant
to be one notch closer to real ops work: reading `docker ps`/`docker logs`,
telling "the service is down" apart from "the service is up but misconfigured,"
and knowing which outages are actually urgent (Postgres down is everything-down;
Grafana down is cosmetic).

Same practice loop as Tier 1: `python manage.py break_infra`, investigate for
real (`docker ps`, `docker logs <container>`), fix it for real, then
`python manage.py verify_infra_fix <ticket_id>`.
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass

import docker
from docker.errors import NotFound

from ops.models import Ticket
from reviews import storage as review_storage

CONTAINERS = {
    "postgres": "mwr-postgres",
    "redis": "mwr-redis",
    "minio": "mwr-minio",
    "prometheus": "mwr-prometheus",
    "grafana": "mwr-grafana",
}


def _docker_client():
    return docker.from_env()


def _container(name: str):
    client = _docker_client()
    try:
        return client.containers.get(CONTAINERS[name])
    except NotFound as exc:
        raise RuntimeError(
            f"Container {CONTAINERS[name]!r} not found — is `docker compose up -d` running?"
        ) from exc


def _is_running(name: str) -> bool:
    try:
        c = _container(name)
        c.reload()
        return c.status == "running"
    except RuntimeError:
        return False


def _redis_reachable() -> bool:
    import redis

    try:
        client = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        return bool(client.ping())
    except Exception:
        return False


def _postgres_reachable() -> bool:
    import psycopg

    try:
        conn = psycopg.connect(
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=os.environ.get("POSTGRES_PORT", "5432"),
            dbname=os.environ.get("POSTGRES_DB", "merchantreview"),
            user=os.environ.get("POSTGRES_USER", "merchantreview"),
            password=os.environ.get("POSTGRES_PASSWORD", "merchantreview"),
            connect_timeout=2,
        )
        conn.close()
        return True
    except Exception:
        return False


def _minio_reachable() -> bool:
    try:
        review_storage._client().list_buckets()
        return True
    except Exception:
        return False


def _retry(check: Callable[[], bool], attempts: int = 5, delay: float = 1.0) -> bool:
    """A just-restarted container's service inside it may take a moment to accept
    connections even once Docker reports the container itself as 'running' — this
    is the real reason naive health checks flap right after a restart."""
    for _ in range(attempts):
        if check():
            return True
        time.sleep(delay)
    return False


@dataclass
class InfraFaultDefinition:
    key: str
    title: str
    description: str
    priority: str
    category: str
    real_cause: str
    fix_hint: str
    inject: Callable[[], dict]
    check_resolved: Callable[[Ticket], bool]


def _inject_stop(name: str) -> dict:
    _container(name).stop(timeout=5)
    return {}


INFRA_FAULTS: dict[str, InfraFaultDefinition] = {
    "redis_down": InfraFaultDefinition(
        key="redis_down",
        title="Submitted reviews never leave 'queued'",
        description=(
            "The API accepts new merchant submissions fine and creates review records, but "
            "nothing ever progresses past the 'queued' status — no scraping, no analysis."
        ),
        priority="critical",
        category="infra",
        real_cause="The Redis container (Celery's broker) was stopped — tasks are being "
        "enqueued but nothing can carry them to a worker.",
        fix_hint="`docker ps -a` will show mwr-redis as Exited. `docker start mwr-redis` "
        "(or `docker compose up -d redis`) brings it back; confirm with `redis-cli ping`.",
        inject=lambda: _inject_stop("redis"),
        check_resolved=lambda t: _is_running("redis") and _retry(_redis_reachable),
    ),
    "postgres_down": InfraFaultDefinition(
        key="postgres_down",
        title="The entire API is returning server errors",
        description=(
            "Every API endpoint — including simple reads — is failing. This looks broader "
            "than a single feature being broken."
        ),
        priority="critical",
        category="infra",
        real_cause="The Postgres container was stopped. Nothing in a Django app can do "
        "anything without its database, which is exactly why this should be the first "
        "thing checked on a 'everything is broken' report.",
        fix_hint="`docker ps -a` shows mwr-postgres Exited. `docker start mwr-postgres`, "
        "then give it a few seconds to accept connections before assuming it's still broken.",
        inject=lambda: _inject_stop("postgres"),
        check_resolved=lambda t: _is_running("postgres") and _retry(_postgres_reachable),
    ),
    "minio_down": InfraFaultDefinition(
        key="minio_down",
        title="Reviews get stuck after scraping, before completing",
        description=(
            "Reviews reach the 'analyzing' status but never complete; Celery worker logs "
            "mention a connection error around the point evidence would normally be stored."
        ),
        priority="high",
        category="infra",
        real_cause="The MinIO container was stopped, so `store_snapshot()` can't reach "
        "object storage at all — a connection-level failure, not a missing-bucket one.",
        fix_hint="`docker start mwr-minio`. Confirm with the MinIO console "
        "(http://localhost:9011) or `awslocal`-style `boto3` `list_buckets()`.",
        inject=lambda: _inject_stop("minio"),
        check_resolved=lambda t: _is_running("minio") and _retry(_minio_reachable),
    ),
    "minio_bucket_missing": InfraFaultDefinition(
        key="minio_bucket_missing",
        title="Storage writes failing with a 'no such bucket' style error",
        description=(
            "MinIO itself appears to be up and reachable, but review evidence storage is "
            "still failing — the error references the snapshot bucket specifically, not a "
            "connection problem."
        ),
        priority="medium",
        category="infra",
        real_cause="MinIO is running fine — the snapshot bucket itself was deleted. This is "
        "deliberately different from `minio_down`: the service is healthy, the configuration/"
        "state it depends on is not. Confusing these two is a common real mistake.",
        fix_hint="Recreate the bucket: `reviews.storage.ensure_bucket_exists()` from a Django "
        "shell, or `mc mb local/merchant-review-snapshots` if using the MinIO CLI.",
        inject=lambda: _delete_bucket(),
        check_resolved=lambda t: _minio_reachable() and _bucket_exists(),
    ),
    "grafana_down": InfraFaultDefinition(
        key="grafana_down",
        title="Dashboards are unreachable",
        description=(
            "Grafana is returning connection errors. Before escalating, check whether this "
            "is actually affecting the review pipeline itself or just visibility into it."
        ),
        priority="low",
        category="infra",
        real_cause="The Grafana container was stopped. Core functionality (Django, Celery, "
        "Postgres, Redis, MinIO) is entirely unaffected — this is a monitoring-visibility "
        "outage, not a production outage, and should be triaged accordingly.",
        fix_hint="`docker start mwr-grafana`.",
        inject=lambda: _inject_stop("grafana"),
        check_resolved=lambda t: _is_running("grafana"),
    ),
}


def _delete_bucket() -> dict:
    client = review_storage._client()
    bucket = review_storage._bucket()
    try:
        objects = client.list_objects_v2(Bucket=bucket).get("Contents", [])
        if objects:
            client.delete_objects(
                Bucket=bucket, Delete={"Objects": [{"Key": o["Key"]} for o in objects]}
            )
        client.delete_bucket(Bucket=bucket)
    except Exception:
        pass
    return {}


def _bucket_exists() -> bool:
    try:
        review_storage._client().head_bucket(Bucket=review_storage._bucket())
        return True
    except Exception:
        return False


def inject_random_infra_fault() -> Ticket:
    import random

    return inject_infra_fault(random.choice(list(INFRA_FAULTS)))


def inject_infra_fault(key: str) -> Ticket:
    """Files the ticket *before* actually breaking anything — deliberately, since
    a fault like postgres_down would otherwise take down the very database the
    ticket needs to be written to. Mirrors how a real monitoring/paging system
    logs an incident as it starts, not after the dust settles."""
    fault = INFRA_FAULTS[key]
    ticket = Ticket.objects.create(
        title=fault.title,
        description=fault.description,
        priority=fault.priority,
        category=fault.category,
        source="fault_injection",
        fault_key=fault.key,
    )
    extra = fault.inject()
    if extra:
        for field, value in extra.items():
            setattr(ticket, field, value)
        ticket.save(update_fields=list(extra))
    return ticket


def verify_infra_fix(ticket: Ticket) -> bool:
    from django.utils import timezone

    fault = INFRA_FAULTS.get(ticket.fault_key)
    if fault is None:
        return False
    resolved = fault.check_resolved(ticket)
    if resolved and ticket.status not in ("resolved", "closed"):
        ticket.status = "resolved"
        ticket.resolved_at = timezone.now()
        ticket.save(update_fields=["status", "resolved_at"])
    return resolved
