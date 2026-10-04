"""
Load the bundled demo stock file so a fresh install shows a working
system immediately:

    python manage.py seed_demo
    python manage.py seed_demo --csv path/to/file.csv --reset
"""
from django.core.management.base import BaseCommand, CommandError

from inventory.models import Item
from inventory.services.csvio import import_rows


class Command(BaseCommand):
    help = "Seed the database with the bundled sample stock CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            type=str,
            default="data/sample_stock.csv",
            help="CSV file to import (default: data/sample_stock.csv).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all existing items first.",
        )

    def handle(self, *args, **options):
        from pathlib import Path

        path = Path(options["csv"])
        if not path.exists():
            raise CommandError(
                "Sample CSV not found at %s (run from the project root)." % path
            )

        if options["reset"]:
            deleted = Item.objects.all().delete()
            self.stdout.write(
                self.style.WARNING("Reset: removed %d existing row(s)." % deleted[0])
            )

        import csv as py_csv

        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = py_csv.DictReader(fh)
            result = import_rows(reader, update_existing=False, source="seed_demo")

        self.stdout.write(
            self.style.SUCCESS(
                "Seeded %d item(s) (%d skipped)."
                % (len(result["created"]), len(result["skipped"]))
            )
        )
        self.stdout.write("Try: python manage.py check_stock")
