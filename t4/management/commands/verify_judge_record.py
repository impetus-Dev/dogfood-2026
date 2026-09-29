import sys
from django.core.management.base import BaseCommand
from t4.models import JudgeRecord
from t4.services import get_public_key, verify_payload_signature


class Command(BaseCommand):
    help = "Perform offline cryptographic verification of a JudgeRecord signature."

    def add_arguments(self, parser):
        parser.add_argument("record_id", type=str, help="ID of the JudgeRecord to verify")

    def handle(self, *args, **options):
        record_id_str = options["record_id"]

        if not str(record_id_str).isdigit() or int(record_id_str) <= 0:
            self.stderr.write(self.style.ERROR(f"Invalid record ID: {record_id_str}"))
            sys.exit(1)

        record_id = int(record_id_str)
        try:
            record = JudgeRecord.objects.get(pk=record_id)
        except JudgeRecord.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"JudgeRecord #{record_id} not found."))
            sys.exit(1)

        pub_key = get_public_key()
        sig_bytes = bytes(record.signature)
        valid = verify_payload_signature(
            record.payload,
            sig_bytes,
            public_key=pub_key,
        )

        if valid:
            self.stdout.write(
                self.style.SUCCESS(f"JudgeRecord #{record_id} signature: VALID")
            )
        else:
            self.stderr.write(
                self.style.ERROR(f"JudgeRecord #{record_id} signature: INVALID")
            )
            sys.exit(1)
