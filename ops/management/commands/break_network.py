from django.core.management.base import BaseCommand

from ops import network_faults


class Command(BaseCommand):
    help = (
        "Tier 3: inject real infrastructure drift into the Pulumi/AWS layer "
        "(verified against LocalStack) and file a ticket for it."
    )

    def add_arguments(self, parser):
        parser.add_argument("--fault", choices=list(network_faults.NETWORK_FAULTS), default=None)

    def handle(self, *args, **options):
        fault_key = options["fault"]
        ticket = (
            network_faults.inject_network_fault(fault_key)
            if fault_key
            else network_faults.inject_random_network_fault()
        )
        self.stdout.write(self.style.WARNING(f"Filed ticket {ticket.id}"))
        self.stdout.write(f"  Title:       {ticket.title}")
        self.stdout.write(f"  Priority:    {ticket.priority}")
        self.stdout.write(f"  Description: {ticket.description}")
        self.stdout.write("")
        self.stdout.write(
            "Start with `aws ec2 describe-...` / `aws elbv2 describe-...` against LocalStack "
            "(awslocal), and compare against infra/*.py."
        )
        self.stdout.write(f"When fixed: python manage.py verify_network_fix {ticket.id}")
