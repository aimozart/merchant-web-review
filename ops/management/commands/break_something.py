from django.core.management.base import BaseCommand

from ops import faults


class Command(BaseCommand):
    help = "Inject one fault (random, or a specific --fault key) and file a ticket for it."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fault", choices=list(faults.FAULTS), default=None,
            help="Inject this specific fault instead of a random one.",
        )

    def handle(self, *args, **options):
        fault_key = options["fault"]
        ticket = faults.inject_fault(fault_key) if fault_key else faults.inject_random_fault()
        self.stdout.write(self.style.WARNING(f"Filed ticket {ticket.id}"))
        self.stdout.write(f"  Title:       {ticket.title}")
        self.stdout.write(f"  Priority:    {ticket.priority}")
        self.stdout.write(f"  Category:    {ticket.category}")
        self.stdout.write(f"  Description: {ticket.description}")
        self.stdout.write("")
        self.stdout.write(
            "Go investigate. When you think it's fixed: "
            f"python manage.py verify_fix {ticket.id}"
        )
