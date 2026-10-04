"""
The daily sentinel:  python manage.py check_stock

What it does (in order):
  1. Loops through every active item, compares quantity vs reorder
     threshold and collects everything that needs restocking.
  2. Writes StockAlert snapshots so the web app keeps a history.
  3. Prints a clean console report.
  4. Writes a dated TXT + CSV report (and stable latest_* copies) into
     REPORT_DIR so other systems/emails can pick them up.
  5. Optionally emails the report when SMTP env vars + --email are set.

Schedule it with cron (macOS/Linux) or Task Scheduler (Windows) - see
README.md, section "The daily job".
"""
import sys

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from inventory.nlp.summary import morning_briefing
from inventory.services.stock import build_restock_report, refresh_alerts


class Command(BaseCommand):
    help = "Check stock levels against reorder thresholds and generate the restock report."

    def add_arguments(self, parser):
        parser.add_argument(
            "--report-dir",
            type=str,
            default=None,
            help="Directory for the TXT/CSV reports (default: REPORT_DIR setting).",
        )
        parser.add_argument(
            "--no-files",
            action="store_true",
            help="Only print to console; skip writing report files.",
        )
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="Suppress the full table; print only the summary line.",
        )
        parser.add_argument(
            "--no-exit",
            action="store_true",
            help="Always exit 0 even when restock is needed (default: exit 2 "
            "when items need restocking, useful for shell automation).",
        )
        parser.add_argument(
            "--email",
            action="store_true",
            help="Email the report (requires EMAIL_* settings).",
        )

    def handle(self, *args, **options):
        report = build_restock_report(
            report_dir=options["report_dir"],
            write_files=not options["no_files"],
        )
        alerts = refresh_alerts()

        stats = report["stats"]
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("StockWise - daily stock check"))
        if not options["quiet"]:
            self.stdout.write(report["text"])
        self.stdout.write(
            self.style.NOTICE(
                "Summary: %d checked | %d need restocking (%d low, %d out)"
                % (stats["total"], len(report["rows"]), stats["low"], stats["out"])
            )
        )
        self.stdout.write(self.style.NOTICE("Briefing: %s" % morning_briefing()))
        if report["txt_path"]:
            self.stdout.write(
                "Reports written: %s | %s" % (report["txt_path"], report["csv_path"])
            )
        self.stdout.write("New alert snapshots: %d" % len(alerts))

        if options["email"]:
            self._send(report)

        # Exit code 2 when something needs restocking: handy for shell
        # automation (does not affect cron's notion of a crash = 1).
        if report["rows"] and not options["no_exit"]:
            sys.exit(2)

    def _send(self, report):
        recipient = getattr(settings, "STOCK_ALERT_EMAIL_TO", "")
        if not getattr(settings, "EMAIL_HOST", None) or not recipient:
            self.stdout.write(
                self.style.WARNING(
                    "Email skipped: set EMAIL_HOST... and STOCK_ALERT_EMAIL_TO "
                    "in the environment to enable delivery."
                )
            )
            return
        send_mail(
            subject="StockWise restock report - %d item(s) need attention"
            % len(report["rows"]),
            message=report["text"],
            from_email=getattr(settings, "EMAIL_HOST_USER", "stockwise@localhost"),
            recipient_list=[recipient],
            fail_silently=False,
        )
        self.stdout.write(self.style.SUCCESS("Report emailed to %s" % recipient))
