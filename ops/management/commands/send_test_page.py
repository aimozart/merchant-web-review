import requests
from django.core.management.base import BaseCommand, CommandError

from ops.tasks import NTFY_TOPIC


class Command(BaseCommand):
    help = "Send a one-off test push notification to verify NTFY_TOPIC is configured correctly."

    def handle(self, *args, **options):
        if not NTFY_TOPIC:
            raise CommandError("NTFY_TOPIC is not set in .env")

        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=b"Test page from the merchant-web-review on-call trainer. If you got this, paging works.",
            headers={"Title": "[TEST] On-call paging works", "Tags": "white_check_mark"},
            timeout=5,
        )
        self.stdout.write(self.style.SUCCESS(f"Sent test notification to ntfy.sh/{NTFY_TOPIC}"))
