from django.core.management.base import BaseCommand

from ops import faults


class Command(BaseCommand):
    help = "List every available fault-injection scenario (no cause/fix shown — use --reveal on a real ticket for that)."

    def handle(self, *args, **options):
        for key, fault in faults.FAULTS.items():
            self.stdout.write(self.style.WARNING(f"{key}  ({fault.priority}/{fault.category})"))
            self.stdout.write(f"  {fault.title}")
