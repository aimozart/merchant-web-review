"""
Two Celery tasks that turn the SRE trainer into a standing practice environment
instead of a one-shot demo:

- `replenish_ticket` keeps the queue from ever running dry — fired after a
  ticket closes (see ops/views.py TicketViewSet.close), so clearing tickets is
  what produces new ones, the same shape as a real ticket queue during an
  8-10 hour practice shift.
- `maybe_page_oncall` simulates being genuinely paged: most runs do nothing
  (real on-call is quiet far more often than it pages), and on the rare run
  that rolls a page, it injects a fault and pushes a real notification via
  ntfy.sh — deliberately independent of any Claude/chat session being open,
  since a real on-call shift doesn't require that either.
"""
from __future__ import annotations

import logging
import os
import random

import requests
from celery import shared_task

from ops import faults, infra_faults, network_faults
from ops.models import Ticket

logger = logging.getLogger(__name__)

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

# This task is scheduled hourly (see `seed_periodic_tasks`). Targeting roughly
# one page per two days of practice means an expected value of ~1 event per
# 48 hourly runs — real on-call is mostly silence punctuated by rare pages,
# not several incidents a shift.
PAGE_PROBABILITY_PER_HOURLY_CHECK = 1 / 48


def _docker_reachable() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


def _localstack_reachable() -> bool:
    try:
        resp = requests.get("http://localhost:4566/_localstack/health", timeout=1)
        return resp.status_code == 200
    except Exception:
        return False


def _inject_from_available_tier(prefer_reliable: bool = False) -> Ticket:
    """Injects one random fault from a tier whose dependencies are actually
    reachable right now. `prefer_reliable` restricts to Tier 1 (no external
    dependencies) — used for unattended on-call paging, where a "page" whose
    Tier 2/3 infra isn't even running would just be a confusing false alarm
    rather than realistic practice."""
    tiers = [(1, faults.inject_random_fault)]
    if not prefer_reliable:
        if _docker_reachable():
            tiers.append((2, infra_faults.inject_random_infra_fault))
        if _localstack_reachable():
            tiers.append((3, network_faults.inject_random_network_fault))

    tier, inject = random.choice(tiers)
    try:
        return inject()
    except Exception:
        logger.exception("Fault injection failed for tier %s, falling back to Tier 1", tier)
        return faults.inject_random_fault()


@shared_task
def replenish_ticket() -> str:
    ticket = _inject_from_available_tier()
    logger.info("Replenished ticket queue: %s", ticket.title)
    return str(ticket.id)


@shared_task
def maybe_page_oncall() -> str | None:
    if random.random() >= PAGE_PROBABILITY_PER_HOURLY_CHECK:
        return None

    ticket = _inject_from_available_tier(prefer_reliable=True)

    if NTFY_TOPIC:
        try:
            requests.post(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                data=ticket.description.encode("utf-8"),
                headers={
                    "Title": f"[PAGE] {ticket.title}",
                    "Priority": {"critical": "urgent", "high": "high"}.get(ticket.priority, "default"),
                    "Tags": "rotating_light",
                },
                timeout=5,
            )
        except Exception:
            logger.exception("Failed to send on-call page notification")
    else:
        logger.warning("NTFY_TOPIC not configured — page fired but no notification sent")

    logger.warning("On-call page fired: %s", ticket.title)
    return str(ticket.id)
