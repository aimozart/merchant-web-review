"""
The async Web Presence Review pipeline. Runs as a Celery task rather than inline in
the request/response cycle because scraping + LLM analysis can take several seconds
— exactly the kind of external-API-dependent workflow this role's job description
calls out (queue-based async systems, workflows that depend on third-party APIs).
"""
from __future__ import annotations

import logging
from dataclasses import asdict

from celery import shared_task
from django.utils import timezone
from prometheus_client import Counter, Histogram

from . import storage
from .llm import analyze
from .models import Merchant, RiskSignal, WebPresenceReview
from .scraping import gather_web_presence

logger = logging.getLogger(__name__)

REVIEWS_STARTED = Counter(
    "merchant_reviews_started_total", "Web Presence Reviews started", ["is_monitoring_check"]
)
REVIEWS_COMPLETED = Counter(
    "merchant_reviews_completed_total",
    "Web Presence Reviews completed, by outcome",
    ["recommendation"],
)
REVIEWS_FAILED = Counter("merchant_reviews_failed_total", "Web Presence Reviews that errored")
REVIEW_DURATION = Histogram(
    "merchant_review_duration_seconds", "End-to-end duration of a Web Presence Review"
)


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def run_web_presence_review(self, review_id: str):
    """
    Orchestrates one full Web Presence Review: fetch the site, store the raw
    snapshot as evidence, run LLM analysis, persist the structured recommendation
    and risk signals. Retries on transient failure (e.g. a network blip) before
    giving up and marking the review failed — never silently drops a review.
    """
    review = WebPresenceReview.objects.select_related("merchant").get(id=review_id)
    REVIEWS_STARTED.labels(is_monitoring_check=str(review.is_monitoring_check)).inc()

    with REVIEW_DURATION.time():
        try:
            review.status = "scraping"
            review.save(update_fields=["status"])

            snapshot = gather_web_presence(review.merchant.website_url)
            object_key = storage.store_snapshot(str(review.id), asdict(snapshot))
            review.snapshot_object_key = object_key
            review.status = "analyzing"
            review.save(update_fields=["snapshot_object_key", "status"])

            result = analyze(snapshot, review.merchant.business_name)

            review.recommendation = result.recommendation
            review.summary = result.summary
            review.status = "complete"
            review.completed_at = timezone.now()
            review.save(
                update_fields=["recommendation", "summary", "status", "completed_at"]
            )

            RiskSignal.objects.bulk_create(
                [
                    RiskSignal(
                        review=review,
                        category=s.category,
                        severity=s.severity,
                        label=s.label,
                        detail=s.detail,
                    )
                    for s in result.signals
                ]
            )
            REVIEWS_COMPLETED.labels(recommendation=result.recommendation).inc()

        except Exception as exc:
            logger.exception("Web Presence Review %s failed", review_id)
            REVIEWS_FAILED.inc()
            if self.request.retries >= self.max_retries:
                review.status = "failed"
                review.error_message = str(exc)
                review.save(update_fields=["status", "error_message"])
                return
            # Passing exc= here would make Celery re-raise it directly instead
            # of MaxRetriesExceededError once retries are exhausted — checking
            # request.retries above ourselves is what makes the "mark failed"
            # branch above actually reachable.
            self.retry(exc=exc)


@shared_task
def run_due_monitoring_checks():
    """
    Merchant Monitoring — TrueBiz's term for ongoing, periodic re-checks of a
    merchant already onboarded, rather than a one-time review. Runs on a Celery
    Beat schedule (see admin/django-celery-beat config); finds every merchant with
    monitoring enabled whose last review is older than its configured interval and
    queues a fresh review for each.
    """
    from datetime import timedelta

    now = timezone.now()
    due_count = 0
    for merchant in Merchant.objects.filter(monitoring_enabled=True):
        last_review = merchant.reviews.order_by("-created_at").first()
        interval = timedelta(hours=merchant.monitoring_interval_hours)
        if last_review is None or (now - last_review.created_at) >= interval:
            new_review = WebPresenceReview.objects.create(
                merchant=merchant, is_monitoring_check=True
            )
            run_web_presence_review.delay(str(new_review.id))
            due_count += 1
    return due_count
