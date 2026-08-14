from django.core.management.base import BaseCommand, CommandError

from ops import faults
from ops.models import Ticket


class Command(BaseCommand):
    help = "Re-check real system state for a fault-injection ticket and resolve it if genuinely fixed."

    def add_arguments(self, parser):
        parser.add_argument("ticket_id")

    def handle(self, *args, **options):
        try:
            ticket = Ticket.objects.get(id=options["ticket_id"])
        except Ticket.DoesNotExist:
            raise CommandError("No such ticket.")

        if not ticket.fault_key:
            raise CommandError("This ticket wasn't filed by the fault-injection tool.")

        resolved = faults.verify_fix(ticket)
        if resolved:
            self.stdout.write(self.style.SUCCESS(f"Fixed. Ticket {ticket.id} marked resolved."))
            self.stdout.write("Close it out with the API's /tickets/{id}/close/ action, or via admin.")
        else:
            self.stdout.write(self.style.ERROR("Still broken — the underlying condition is still present."))
