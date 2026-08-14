from django.core.management.base import BaseCommand
from django_celery_beat.models import IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = (
        "Idempotently create the Celery Beat schedules this project relies on "
        "(Merchant Monitoring re-checks, on-call paging). Safe to re-run."
    )

    def handle(self, *args, **options):
        every_15_min, _ = IntervalSchedule.objects.get_or_create(
            every=15, period=IntervalSchedule.MINUTES
        )
        hourly, _ = IntervalSchedule.objects.get_or_create(
            every=1, period=IntervalSchedule.HOURS
        )

        PeriodicTask.objects.update_or_create(
            name="Run due monitoring checks",
            defaults={
                "interval": every_15_min,
                "crontab": None,
                "task": "reviews.tasks.run_due_monitoring_checks",
            },
        )
        PeriodicTask.objects.update_or_create(
            name="Maybe page on-call",
            defaults={
                "interval": hourly,
                "crontab": None,
                "task": "ops.tasks.maybe_page_oncall",
            },
        )

        self.stdout.write(self.style.SUCCESS("Periodic tasks seeded."))
        self.stdout.write(
            "Requires `celery -A merchantreview beat` running to actually fire on schedule."
        )
