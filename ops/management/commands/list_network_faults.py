from django.core.management.base import BaseCommand

from ops import network_faults


class Command(BaseCommand):
    help = "List every Tier 3 (real networking / Pulumi-AWS drift) fault scenario."

    def handle(self, *args, **options):
        for key, fault in network_faults.NETWORK_FAULTS.items():
            self.stdout.write(self.style.WARNING(f"{key}  ({fault.priority}/{fault.category})"))
            self.stdout.write(f"  {fault.title}")
