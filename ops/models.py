import uuid

from django.db import models


class Ticket(models.Model):
    """
    An internal ops/support ticket — filed either by the hourly health-check task
    (real anomaly detection) or by the fault-injection practice tool (see faults.py).
    Both paths write the same model, on purpose: from the ticket queue's point of
    view, a real production issue and a practice one look identical, which is the
    whole point of the exercise.
    """

    STATUS_CHOICES = [
        ("open", "Open"),
        ("in_progress", "In Progress"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
    ]

    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    CATEGORY_CHOICES = [
        ("infra", "Infrastructure"),
        ("data", "Data Integrity"),
        ("integration", "Third-Party Integration"),
        ("performance", "Performance"),
    ]

    SOURCE_CHOICES = [
        ("health_check", "Automated Health Check"),
        ("fault_injection", "Fault Injection Practice"),
        ("manual", "Manually Filed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(help_text="Symptom only — not the root cause.")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="medium")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="infra")
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="manual")

    # Set only by fault-injection practice tickets — the practice tool's own
    # bookkeeping to know which fault + verification check this ticket maps to.
    # Never surfaced in the API/admin list view; only read by `verify_fix`/`reveal_fault`.
    fault_key = models.CharField(max_length=100, blank=True)

    related_merchant = models.ForeignKey(
        "reviews.Merchant", null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets"
    )
    related_review = models.ForeignKey(
        "reviews.WebPresenceReview", null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets"
    )

    resolution_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"[{self.priority}/{self.status}] {self.title}"


class OpsFlag(models.Model):
    """
    Tiny runtime-checked key/value store for conditions that need to be toggled
    without a redeploy — the same feature-flag pattern a real ops team uses, and
    the mechanism a couple of fault-injection scenarios use to simulate a broken
    dependency (e.g. 'force the LLM path to look unavailable') without actually
    touching real credentials or infrastructure.
    """

    key = models.CharField(max_length=100, primary_key=True)
    value = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True)

    @classmethod
    def is_set(cls, key: str) -> bool:
        return cls.objects.filter(key=key, value=True).exists()

    @classmethod
    def set_flag(cls, key: str, value: bool, note: str = ""):
        cls.objects.update_or_create(key=key, defaults={"value": value, "note": note})

    def __str__(self):
        return f"{self.key}={self.value}"
