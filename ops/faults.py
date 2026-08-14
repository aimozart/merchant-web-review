"""
Fault-injection registry for SRE practice: "you break it, I fix it."

Each fault mutates real, running system state in a small, safe, fully reversible
way, then files a Ticket describing only the *symptom* a real on-call engineer
would see — never the cause. `verify_fix()` re-checks actual system state, so a
ticket can only be closed once the underlying problem is genuinely gone, not just
marked done. `--reveal` (see management/commands/reveal_fault.py) is the escape
hatch for when you're stuck, showing the real cause and a suggested fix.

Deliberately model-only / DB-only faults — nothing here touches real MinIO, Redis,
or LocalStack infrastructure, so every fault is instant to inject and to fully
undo, and never requires tearing down a container to reset.
"""
from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from ops.models import OpsFlag, Ticket
from reviews.models import Merchant, RiskSignal, WebPresenceReview


@dataclass
class FaultDefinition:
    key: str
    title: str
    description: str  # symptom only, shown on the ticket
    priority: str
    category: str
    real_cause: str  # only shown via --reveal
    fix_hint: str  # only shown via --reveal
    inject: Callable[[], dict]  # returns extra Ticket field overrides (e.g. related_merchant)
    check_resolved: Callable[[Ticket], bool]


def _get_or_create_demo_merchant() -> Merchant:
    merchant, _ = Merchant.objects.get_or_create(
        website_url="https://example-demo-merchant.local",
        defaults={"business_name": "Example Demo Merchant", "monitoring_enabled": True},
    )
    return merchant


# ---------------------------------------------------------------------------
# 1. Stuck review — simulates a Celery task that died mid-flight and never
#    updated the review past "analyzing" (e.g. worker OOM-killed, task lost).
# ---------------------------------------------------------------------------

def _inject_stuck_review() -> dict:
    merchant = _get_or_create_demo_merchant()
    review = WebPresenceReview.objects.create(merchant=merchant, status="analyzing")
    WebPresenceReview.objects.filter(id=review.id).update(
        created_at=timezone.now() - timedelta(hours=3)
    )
    return {"related_merchant": merchant, "related_review": review}


def _check_stuck_review(ticket: Ticket) -> bool:
    if ticket.related_review_id is None:
        return True
    review = WebPresenceReview.objects.filter(id=ticket.related_review_id).first()
    return review is None or review.status in ("complete", "failed")


# ---------------------------------------------------------------------------
# 2. Overdue monitoring — simulates Celery Beat silently not running (or its
#    schedule getting disabled) so a monitored merchant stops being re-checked.
# ---------------------------------------------------------------------------

def _inject_overdue_monitoring() -> dict:
    merchant = _get_or_create_demo_merchant()
    merchant.monitoring_enabled = True
    merchant.monitoring_interval_hours = 24
    merchant.save(update_fields=["monitoring_enabled", "monitoring_interval_hours"])
    review = WebPresenceReview.objects.create(merchant=merchant, status="complete")
    WebPresenceReview.objects.filter(id=review.id).update(
        created_at=timezone.now() - timedelta(hours=60),
        completed_at=timezone.now() - timedelta(hours=60),
    )
    return {"related_merchant": merchant}


def _check_overdue_monitoring(ticket: Ticket) -> bool:
    if ticket.related_merchant_id is None:
        return True
    merchant = Merchant.objects.filter(id=ticket.related_merchant_id).first()
    if merchant is None or not merchant.monitoring_enabled:
        return True
    last_review = merchant.reviews.order_by("-created_at").first()
    if last_review is None:
        return False
    return (timezone.now() - last_review.created_at) < timedelta(
        hours=merchant.monitoring_interval_hours * 2
    )


# ---------------------------------------------------------------------------
# 3. Degraded LLM analysis — flips a feature flag that forces every review to
#    silently use the deterministic rule-based fallback instead of the LLM,
#    simulating a bad config/flag left on rather than a hard API failure.
# ---------------------------------------------------------------------------

def _inject_llm_degraded() -> dict:
    OpsFlag.set_flag("llm_analysis_disabled", True, note="Injected by break_something")
    return {}


def _check_llm_degraded(ticket: Ticket) -> bool:
    return not OpsFlag.is_set("llm_analysis_disabled")


# ---------------------------------------------------------------------------
# 4. Bad signal category — simulates a data-quality bug where a risk signal
#    lands with a category value that doesn't match any known choice, which
#    would silently break any UI/report that groups signals by category.
# ---------------------------------------------------------------------------

def _inject_bad_signal_category() -> dict:
    merchant = _get_or_create_demo_merchant()
    review = WebPresenceReview.objects.create(merchant=merchant, status="complete")
    WebPresenceReview.objects.filter(id=review.id).update(completed_at=timezone.now())
    RiskSignal.objects.create(
        review=review,
        category="legacy_import",
        severity="medium",
        label="Signal from a legacy import",
        detail="Category value predates the current category taxonomy.",
    )
    return {"related_merchant": merchant, "related_review": review}


def _check_bad_signal_category(ticket: Ticket) -> bool:
    valid_categories = {c for c, _ in RiskSignal.CATEGORY_CHOICES}
    qs = RiskSignal.objects.all()
    if ticket.related_review_id:
        qs = qs.filter(review_id=ticket.related_review_id)
    return not qs.exclude(category__in=valid_categories).exists()


# ---------------------------------------------------------------------------
# 5. Failure spike — simulates several reviews failing in a short window
#    (e.g. the scrape target's WAF started blocking the reviewer's IP).
# ---------------------------------------------------------------------------

FAILURE_SPIKE_MARKER = "Simulated failure for SRE practice (break_something)"


def _inject_failure_spike() -> dict:
    merchant = _get_or_create_demo_merchant()
    for _ in range(5):
        review = WebPresenceReview.objects.create(
            merchant=merchant, status="failed", error_message=FAILURE_SPIKE_MARKER
        )
        WebPresenceReview.objects.filter(id=review.id).update(
            created_at=timezone.now() - timedelta(minutes=random.randint(1, 45))
        )
    return {"related_merchant": merchant}


def _check_failure_spike(ticket: Ticket) -> bool:
    return not WebPresenceReview.objects.filter(
        status="failed", error_message=FAILURE_SPIKE_MARKER
    ).exists()


FAULTS: dict[str, FaultDefinition] = {
    "stuck_review": FaultDefinition(
        key="stuck_review",
        title="Review stuck in 'Analyzing Risk Signals'",
        description=(
            "A Web Presence Review for a merchant has been sitting in the "
            "'Analyzing Risk Signals' state for an unusually long time and never "
            "completed or failed."
        ),
        priority="high",
        category="infra",
        real_cause=(
            "The Celery task backing this review never ran to completion (simulating a "
            "worker crash/OOM/lost task) — the review row itself was left stuck mid-pipeline."
        ),
        fix_hint=(
            "Confirm the Celery worker is actually running and pointed at the same Redis "
            "the web process uses. Then requeue the stuck review directly: "
            "`run_web_presence_review.delay(str(review.id))` from a Django shell, or write a "
            "small management command that finds reviews stuck >1hr in a non-terminal state "
            "and requeues them automatically (this is exactly what the hourly health check "
            "does for real production stuck reviews)."
        ),
        inject=_inject_stuck_review,
        check_resolved=_check_stuck_review,
    ),
    "overdue_monitoring": FaultDefinition(
        key="overdue_monitoring",
        title="Monitored merchant has not been re-reviewed on schedule",
        description=(
            "A merchant with Merchant Monitoring enabled has gone well past its configured "
            "monitoring interval without a fresh review being queued."
        ),
        priority="medium",
        category="infra",
        real_cause=(
            "Simulates Celery Beat's schedule silently not firing (disabled schedule entry, "
            "Beat process not running, or its schedule table out of sync) — the periodic task "
            "that queues monitoring reviews never ran for this merchant."
        ),
        fix_hint=(
            "Check `django_celery_beat` PeriodicTask entries in the admin — is the monitoring "
            "task's schedule enabled? Is a Celery Beat process actually running "
            "(`celery -A merchantreview beat`)? As an immediate fix, manually queue the overdue "
            "review: `run_web_presence_review.delay(...)` for the merchant's next review."
        ),
        inject=_inject_overdue_monitoring,
        check_resolved=_check_overdue_monitoring,
    ),
    "llm_degraded": FaultDefinition(
        key="llm_degraded",
        title="Review recommendations look overly generic",
        description=(
            "Recent review summaries read like generic templated text rather than the usual "
            "specific, LLM-generated underwriting summaries — even though the LLM integration "
            "should be active."
        ),
        priority="medium",
        category="integration",
        real_cause=(
            "An OpsFlag named `llm_analysis_disabled` was left set to True, which forces "
            "`reviews/llm.py::analyze()` to always use the deterministic rule-based fallback "
            "regardless of whether a valid GEMINI_API_KEY is configured — a bad feature flag "
            "left on, not an actual API outage."
        ),
        fix_hint=(
            "Check the OpsFlag table/admin for anything unexpectedly set to True. Clear it: "
            "`OpsFlag.objects.filter(key='llm_analysis_disabled').update(value=False)`."
        ),
        inject=_inject_llm_degraded,
        check_resolved=_check_llm_degraded,
    ),
    "bad_signal_category": FaultDefinition(
        key="bad_signal_category",
        title="Risk signals with unrecognized category values",
        description=(
            "The risk-signal breakdown for at least one review contains a category value that "
            "doesn't match any of the known signal categories, which will break anything that "
            "groups or filters signals by category."
        ),
        priority="low",
        category="data",
        real_cause=(
            "A RiskSignal row was written with `category='legacy_import'` — Django "
            "only enforces `choices=` at the form/serializer layer, not the database layer, so "
            "a bad direct write (bulk import, migration, manual DB edit) can silently insert "
            "an invalid value that the ORM will happily read back."
        ),
        fix_hint=(
            "Find the offending row(s): `RiskSignal.objects.exclude(category__in=[c for c, _ "
            "in RiskSignal.CATEGORY_CHOICES])`. Decide the correct category and fix in place. "
            "Longer-term fix: add a DB-level CHECK constraint so this class of bug can't "
            "recur, not just a one-off data patch."
        ),
        inject=_inject_bad_signal_category,
        check_resolved=_check_bad_signal_category,
    ),
    "failure_spike": FaultDefinition(
        key="failure_spike",
        title="Review failure rate spiked",
        description=(
            "Several Web Presence Reviews have failed in a short window. Check "
            "`merchant_reviews_failed_total` in Grafana/Prometheus and the review error "
            "messages for a common root cause before treating these as unrelated one-offs."
        ),
        priority="critical",
        category="performance",
        real_cause=(
            "Simulates an external dependency (e.g. the target site's WAF, or a rate limit) "
            "rejecting several scrape attempts in a row — five reviews were force-marked "
            "'failed' with the same synthetic error message."
        ),
        fix_hint=(
            "Find them: `WebPresenceReview.objects.filter(status='failed', "
            "error_message__startswith='Simulated failure')`. The real fix is re-running each "
            "one: `run_web_presence_review.delay(str(r.id))` — verify_fix only passes once none "
            "remain in the failed state with that marker."
        ),
        inject=_inject_failure_spike,
        check_resolved=_check_failure_spike,
    ),
}


def inject_random_fault() -> Ticket:
    return inject_fault(random.choice(list(FAULTS)))


def inject_fault(key: str) -> Ticket:
    fault = FAULTS[key]
    extra = fault.inject()
    return Ticket.objects.create(
        title=fault.title,
        description=fault.description,
        priority=fault.priority,
        category=fault.category,
        source="fault_injection",
        fault_key=fault.key,
        **extra,
    )


def verify_fix(ticket: Ticket) -> bool:
    fault = FAULTS.get(ticket.fault_key)
    if fault is None:
        return False
    resolved = fault.check_resolved(ticket)
    if resolved and ticket.status not in ("resolved", "closed"):
        ticket.status = "resolved"
        ticket.resolved_at = timezone.now()
        ticket.save(update_fields=["status", "resolved_at"])
    return resolved
