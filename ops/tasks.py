"""
Two Celery tasks that turn the SRE trainer into a standing practice environment
instead of a one-shot demo:

- `replenish_ticket` keeps the queue from ever running dry — fired after a
  ticket closes (see ops/views.py TicketViewSet.close), so clearing tickets is
  what produces new ones, the same shape as a real ticket queue during an
  8-10 hour practice shift.
- `maybe_page_oncall` simulates being genuinely paged: only during off-hours
  and weekends (not the work shift itself — see `_within_page_window`), and
  even then most runs do nothing (real on-call is quiet far more often than
  it pages). On the rare run that rolls a page, it injects a fault and pushes
  a real, escalating notification via ntfy.sh — deliberately independent of
  any Claude/chat session being open, since a real on-call shift doesn't
  require that either.
"""
from __future__ import annotations

import base64
import logging
import os
import random
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from celery import shared_task

from ops import faults, infra_faults, network_faults
from ops.models import Ticket

logger = logging.getLogger(__name__)

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

# Real on-call pages you when the regular working hours' coverage isn't
# there — nights and weekends, not during the workday itself (during the
# 2pm-11pm work shift, you're already present and would just handle things
# directly). So paging is gated to off-hours (default 11pm-7am daily) PLUS
# all day on weekends, not the work shift.
ONCALL_TIMEZONE = ZoneInfo(os.environ.get("ONCALL_TIMEZONE", "America/Phoenix"))
ONCALL_OFFHOURS_START_HOUR = int(os.environ.get("ONCALL_OFFHOURS_START_HOUR", "23"))  # 11pm
ONCALL_OFFHOURS_END_HOUR = int(os.environ.get("ONCALL_OFFHOURS_END_HOUR", "7"))  # 7am

# This task is scheduled hourly (see `seed_periodic_tasks`), and only actually
# rolls when `_within_page_window` is true. Eligible hours per week: 5 weekday
# nights * 8 off-hours + 2 full weekend days * 24h = 88 of 168 hours (~12.6/day
# on average). Targeting roughly one page per two days of practice means an
# expected value of ~1 event per ~25 eligible hourly checks.
PAGE_PROBABILITY_PER_HOURLY_CHECK = 1 / 25


def _within_page_window(now: datetime | None = None) -> bool:
    now = now or datetime.now(tz=ONCALL_TIMEZONE)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6 — paged all weekend
        return True
    hour = now.hour
    # Off-hours wraps past midnight (e.g. 23:00-06:59), so this is an OR, not a range.
    return hour >= ONCALL_OFFHOURS_START_HOUR or hour < ONCALL_OFFHOURS_END_HOUR

# A single push only buzzes a phone briefly by OS design — no amount of ntfy
# "priority" tuning turns a normal notification into an alarm-clock-grade
# alert. What actually works, and is fully under our control server-side, is
# sending several distinct notifications a short interval apart: each one
# re-triggers the phone's vibration independently. Escalation keeps repeating
# until the ticket is acknowledged (via the notification's tap-to-acknowledge
# action button — see ops/views.py TicketViewSet.acknowledge) or a bounded
# max duration is reached, so a truly-unanswered page doesn't tie up a Celery
# worker indefinitely.
PAGE_ESCALATION_INTERVAL_SECONDS = 20
PAGE_ESCALATION_MAX_ATTEMPTS = 30  # ~10 minutes at the interval above

ONCALL_ACK_BASE_URL = os.environ.get("ONCALL_ACK_BASE_URL", "")


def _mime_encode_header(text: str) -> str:
    """HTTP headers are restricted to latin-1 — plain non-ASCII text (e.g. an
    em-dash in a ticket title) raises UnicodeEncodeError deep inside urllib3
    before the request is even sent. ntfy documents RFC 2047 MIME
    encoded-word syntax as the fix for exactly this."""
    if text.isascii():
        return text
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"=?UTF-8?B?{encoded}?="


def _send_page_notification(ticket: Ticket) -> None:
    if not NTFY_TOPIC:
        logger.warning("NTFY_TOPIC not configured — page fired but no notification sent")
        return

    priority = {"critical": "urgent", "high": "high"}.get(ticket.priority, "default")
    headers = {
        "Title": _mime_encode_header(f"[PAGE] {ticket.title}"),
        "Priority": priority,
        "Tags": "rotating_light",
    }
    if ONCALL_ACK_BASE_URL:
        headers["Actions"] = (
            f"http, Acknowledge, {ONCALL_ACK_BASE_URL}/api/tickets/{ticket.id}/acknowledge/, "
            "method=POST, clear=true"
        )

    for attempt in range(PAGE_ESCALATION_MAX_ATTEMPTS):
        try:
            requests.post(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                data=ticket.description.encode("utf-8"),
                headers=headers,
                timeout=5,
            )
        except Exception:
            logger.exception("Failed to send on-call page notification (attempt %d)", attempt + 1)

        time.sleep(PAGE_ESCALATION_INTERVAL_SECONDS)

        ticket.refresh_from_db()
        if ticket.status != "open":
            logger.info("Page acknowledged after %d attempt(s): %s", attempt + 1, ticket.title)
            return

    logger.warning("Page escalation timed out unacknowledged: %s", ticket.title)


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
    if not _within_page_window():
        return None
    if random.random() >= PAGE_PROBABILITY_PER_HOURLY_CHECK:
        return None

    ticket = _inject_from_available_tier(prefer_reliable=True)
    _send_page_notification(ticket)
    logger.warning("On-call page fired: %s", ticket.title)
    return str(ticket.id)
