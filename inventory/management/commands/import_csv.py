"""
Import stock from a CSV file from the command line.

Examples:
    python manage.py import_csv data/sample_stock.csv
    python manage.py import_csv my_stock.csv --update   # update matches
"""
from django.core.management.base import BaseCommand, CommandError

from inventory.services.csvio import import_rows


class Command(BaseCommand):
    help = "Import items from a CSV file (accepts flexible column headers)."

    def add_arguments(self, parser):
        parser.add_argument("path", type=str, help="Path to the CSV file.")
        parser.add_argument(
            "--update",
            action="store_true",
            help="Update existing items (matched by SKU or fuzzy name) "
            "instead of skipping duplicates.",
        )

    def handle(self, *args, **options):
        import csv as py_csv
        from pathlib import Path

        path = Path(options["path"])
        if not path.exists():
            raise CommandError("File not found: %s" % path)

        with path.open(newline="", encoding="utf-8-sig") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            try:
                dialect = py_csv.Sniffer().sniff(sample, delimiters=",;\t")
            except py_csv.Error:
                dialect = py_csv.excel
            reader = py_csv.DictReader(fh, dialect=dialect)

        result = import_rows(reader, update_existing=options["update"])

        self.stdout.write(
            self.style.SUCCESS(
                "Imported %d new, updated %d, skipped %d."
                % (
                    len(result["created"]),
                    len(result["updated"]),
                    len(result["skipped"]),
                )
            )
        )
        for warning in result["warnings"][:10]:
            self.stdout.write(self.style.WARNING(warning))
        for skipped in result["skipped"][:10]:
            self.stdout.write(
                "  skipped row %s (%s): %s"
                % (skipped["row"], skipped.get("name") or "-", skipped["reason"])
            )
