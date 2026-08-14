from django.core.management.base import BaseCommand, CommandError

from ops import network_faults
from ops.models import Ticket


class Command(BaseCommand):
    help = "Re-check real AWS/LocalStack state for a Tier 3 network-drift ticket."

    def add_arguments(self, parser):
        parser.add_argument("ticket_id")

    def handle(self, *args, **options):
        try:
            ticket = Ticket.objects.get(id=options["ticket_id"])
        except Ticket.DoesNotExist:
            raise CommandError("No such ticket.")

        if ticket.fault_key not in network_faults.NETWORK_FAULTS:
            raise CommandError("This ticket isn't a Tier 3 network fault.")

        resolved = network_faults.verify_network_fix(ticket)
        if resolved:
            self.stdout.write(self.style.SUCCESS(f"Fixed. Ticket {ticket.id} marked resolved."))
        else:
            self.stdout.write(self.style.ERROR("Still broken."))
