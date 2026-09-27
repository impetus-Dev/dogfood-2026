from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Seed initial fixtures for the DOGFOOD 2026 hackathon platform."

    def handle(self, *args, **options):
        # Scaffold implementation for Phase 1: ready for fixture logic in later phase
        self.stdout.write(
            self.style.SUCCESS(
                "seed_fixtures: initial scaffold ready (no fixtures loaded in foundation phase)."
            )
        )
