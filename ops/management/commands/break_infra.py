from django.core.management.base import BaseCommand

from ops import infra_faults


class Command(BaseCommand):
    help = (
        "Tier 2: inject a fault into the actual running Docker Compose stack "
        "(random, or a specific --fault key) and file a ticket for it."
    )

    def add_arguments(self, parser):
        parser.add_argument("--fault", choices=list(infra_faults.INFRA_FAULTS), default=None)

    def handle(self, *args, **options):
        fault_key = options["fault"]
        ticket = (
            infra_faults.inject_infra_fault(fault_key)
            if fault_key
            else infra_faults.inject_random_infra_fault()
        )
        self.stdout.write(self.style.WARNING(f"Filed ticket {ticket.id}"))
        self.stdout.write(f"  Title:       {ticket.title}")
        self.stdout.write(f"  Priority:    {ticket.priority}")
        self.stdout.write(f"  Description: {ticket.description}")
        self.stdout.write("")
        self.stdout.write("Start with `docker ps -a` and `docker logs <container>`.")
        self.stdout.write(f"When fixed: python manage.py verify_infra_fix {ticket.id}")
