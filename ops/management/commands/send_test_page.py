from django.core.management.base import BaseCommand, CommandError

from ops.models import Ticket
from ops.tasks import NTFY_TOPIC, ONCALL_ACK_BASE_URL, _send_page_notification


class Command(BaseCommand):
    help = (
        "Send a real test page — repeats every ~20s with a tap-to-acknowledge action "
        "button until acknowledged or ~10 minutes pass. Ctrl+C to stop early."
    )

    def handle(self, *args, **options):
        if not NTFY_TOPIC:
            raise CommandError("NTFY_TOPIC is not set in .env")
        if not ONCALL_ACK_BASE_URL:
            self.stdout.write(self.style.WARNING(
                "ONCALL_ACK_BASE_URL is not set — the notification won't have an "
                "Acknowledge button; it'll just repeat until it times out."
            ))

        ticket = Ticket.objects.create(
            title="Test page — on-call trainer",
            description=(
                "This is a test page from the merchant-web-review on-call trainer. "
                "Tap Acknowledge (expand the notification) to stop it."
            ),
            priority="critical",
            source="manual",
        )
        self.stdout.write(f"Paging ticket {ticket.id} — watch your phone.")
        _send_page_notification(ticket)
        ticket.refresh_from_db()
        if ticket.status == "open":
            self.stdout.write(self.style.WARNING("Timed out unacknowledged."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Acknowledged (status: {ticket.status})."))
