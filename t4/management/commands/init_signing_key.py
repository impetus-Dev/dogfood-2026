from django.core.management.base import BaseCommand
from t4.services import init_signing_key


class Command(BaseCommand):
    help = "Initialize the Ed25519 signing key if not present."

    def handle(self, *args, **options):
        init_signing_key()
        self.stdout.write(self.style.SUCCESS("T4 Ed25519 signing key initialized successfully."))
