from django.core.management.base import BaseCommand, CommandError

from ops import infra_faults
from ops.models import Ticket


class Command(BaseCommand):
    help = "Escape hatch: show the real cause and fix for a Tier 2 infra-fault ticket."

    def add_arguments(self, parser):
        parser.add_argument("ticket_id")

    def handle(self, *args, **options):
        try:
            ticket = Ticket.objects.get(id=options["ticket_id"])
        except Ticket.DoesNotExist:
            raise CommandError("No such ticket.")

        fault = infra_faults.INFRA_FAULTS.get(ticket.fault_key)
        if fault is None:
            raise CommandError("This ticket isn't a Tier 2 infra fault.")

        self.stdout.write(self.style.WARNING("Real cause:"))
        self.stdout.write(f"  {fault.real_cause}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Suggested fix:"))
        self.stdout.write(f"  {fault.fix_hint}")
