import uuid

from django.db import models


class Merchant(models.Model):
    """A business being evaluated — mirrors TrueBiz's core subject of underwriting."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business_name = models.CharField(max_length=255)
    website_url = models.URLField()
    created_at = models.DateTimeField(auto_now_add=True)

    monitoring_enabled = models.BooleanField(
        default=False,
        help_text="If set, this merchant is periodically re-reviewed (Merchant Monitoring).",
    )
    monitoring_interval_hours = models.PositiveIntegerField(default=24)

    def __str__(self):
        return f"{self.business_name} ({self.website_url})"


class WebPresenceReview(models.Model):
    """
    One "Web Presence Review" — TrueBiz's own term for a point-in-time automated
    investigation of a merchant's online footprint, resulting in an underwriting
    recommendation.
    """

    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("scraping", "Gathering Web Presence"),
        ("analyzing", "Analyzing Risk Signals"),
        ("complete", "Complete"),
        ("failed", "Failed"),
    ]

    RECOMMENDATION_CHOICES = [
        ("pass", "Pass"),
        ("fail", "Fail"),
        ("review", "Manual Review Recommended"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name="reviews")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    is_monitoring_check = models.BooleanField(
        default=False, help_text="True if this review was triggered by Merchant Monitoring."
    )

    recommendation = models.CharField(
        max_length=10, choices=RECOMMENDATION_CHOICES, blank=True
    )
    summary = models.TextField(blank=True)

    # Where the raw scraped snapshot lives (MinIO/S3 object key), for audit purposes —
    # the underwriting decision should always be re-derivable from the original evidence.
    snapshot_object_key = models.CharField(max_length=512, blank=True)

    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Review {self.id} — {self.merchant.business_name} ({self.status})"


class RiskSignal(models.Model):
    """
    One individual signal contributing to a review's overall recommendation —
    TrueBiz's product delivers 250+ of these per merchant; this is a small,
    representative set across the same signal categories.
    """

    CATEGORY_CHOICES = [
        ("domain", "Domain & Infrastructure"),
        ("content", "Site Content & Prohibited Categories"),
        ("social", "Social Presence"),
        ("reputation", "Online Reputation"),
    ]

    SEVERITY_CHOICES = [
        ("info", "Informational"),
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    review = models.ForeignKey(
        WebPresenceReview, on_delete=models.CASCADE, related_name="signals"
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="info")
    label = models.CharField(max_length=255)
    detail = models.TextField(blank=True)

    def __str__(self):
        return f"[{self.category}/{self.severity}] {self.label}"
