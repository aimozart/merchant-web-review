from django.core.management.base import BaseCommand

from ops import infra_faults


class Command(BaseCommand):
    help = "List every Tier 2 (Docker Compose/service layer) fault scenario."

    def handle(self, *args, **options):
        for key, fault in infra_faults.INFRA_FAULTS.items():
            self.stdout.write(self.style.WARNING(f"{key}  ({fault.priority}/{fault.category})"))
            self.stdout.write(f"  {fault.title}")
