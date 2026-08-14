from django.core.management.base import BaseCommand, CommandError

from ops import infra_faults
from ops.models import Ticket


class Command(BaseCommand):
    help = "Re-check the real Docker Compose stack for a Tier 2 infra-fault ticket."

    def add_arguments(self, parser):
        parser.add_argument("ticket_id")

    def handle(self, *args, **options):
        try:
            ticket = Ticket.objects.get(id=options["ticket_id"])
        except Ticket.DoesNotExist:
            raise CommandError("No such ticket.")

        if ticket.fault_key not in infra_faults.INFRA_FAULTS:
            raise CommandError("This ticket isn't a Tier 2 infra fault.")

        resolved = infra_faults.verify_infra_fix(ticket)
        if resolved:
            self.stdout.write(self.style.SUCCESS(f"Fixed. Ticket {ticket.id} marked resolved."))
        else:
            self.stdout.write(self.style.ERROR("Still broken."))
