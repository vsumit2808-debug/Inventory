"""
Test suite: low-stock engine, CRUD, CSV import/export, check_stock job,
NLP intents and the RAG pipeline.

Run:  python manage.py test
"""
import csv
import io
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from .models import Item, QueryLog, StockAlert
from .nlp.assistant import answer_question
from .nlp.intent import classify, extract_entities
from .nlp.summary import morning_briefing
from .rag.retriever import retrieve
from .services.csvio import export_csv, import_rows
from .services.stock import build_restock_report, evaluate_rows


def make_item(**overrides):
    defaults = dict(
        name="Test Widget",
        category="Widgets",
        quantity=50,
        reorder_threshold=10,
        unit_price=2.5,
        supplier="Acme",
        location="Shelf 1",
    )
    defaults.update(overrides)
    return Item.objects.create(**defaults)


class StockLogicTests(TestCase):
    def test_evaluate_rows_flags_low_and_out(self):
        rows = [
            {"name": "A", "quantity": 5, "reorder_threshold": 10},   # LOW
            {"name": "B", "quantity": 0, "reorder_threshold": 10},   # OUT
            {"name": "C", "quantity": 99, "reorder_threshold": 10},  # OK
            {"name": "D", "quantity": 10, "reorder_threshold": 10},  # LOW (boundary)
        ]
        restock, stats = evaluate_rows(rows)
        self.assertEqual(stats, {"total": 4, "ok": 1, "low": 2, "out": 1})
        severities = {r["name"]: r["severity"] for r in restock}
        self.assertEqual(severities["A"], "LOW")
        self.assertEqual(severities["B"], "OUT")
        self.assertEqual(severities["D"], "LOW")
        self.assertNotIn("C", severities)

    def test_suggested_order_prefers_configured_quantity(self):
        restock, _ = evaluate_rows(
            [{"name": "A", "quantity": 2, "reorder_threshold": 10, "reorder_quantity": 55}]
        )
        self.assertEqual(restock[0]["suggested_order"], 55)

    def test_item_properties(self):
        item = make_item(quantity=3, reorder_threshold=10, reorder_quantity=0)
        self.assertTrue(item.needs_reorder)
        self.assertEqual(item.status, Item.Status.LOW)
        self.assertEqual(item.shortfall, 7)
        self.assertEqual(item.suggested_order, 7)
        out = make_item(name="Zero", quantity=0)
        self.assertEqual(out.status, Item.Status.OUT)
        ok = make_item(name="Fine", quantity=100)
        self.assertEqual(ok.status, Item.Status.OK)
        self.assertFalse(ok.needs_reorder)


class ModelTests(TestCase):
    def test_sku_auto_generated(self):
        item = make_item()
        self.assertTrue(item.sku.startswith("ITM-"))


class CSVTests(TestCase):
    def test_import_with_flexible_headers_and_fuzzy_dedupe(self):
        raw = (
            "Item Name,Current Quantity,Reorder Threshold\n"
            "Stapler Heavy Duty,25,5\n"
            "stapler heavy duty,99,5\n"  # fuzzy duplicate -> skipped
        )
        reader = csv.DictReader(io.StringIO(raw))
        result = import_rows(reader)
        self.assertEqual(len(result["created"]), 1)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertIn("duplicate", result["skipped"][0]["reason"])

    def test_import_update_mode_updates_existing(self):
        make_item(name="Stapler Heavy Duty", quantity=25, reorder_threshold=5)
        raw = "Item Name,Current Quantity\nStapler Heavy Duty,60\n"
        result = import_rows(csv.DictReader(io.StringIO(raw)), update_existing=True)
        self.assertEqual(len(result["updated"]), 1)
        self.assertEqual(Item.objects.get().quantity, 60)

    def test_export_csv_roundtrip(self):
        make_item(name="Export Me", quantity=7)
        content = export_csv()
        self.assertIn("Export Me", content)
        self.assertIn("Current Quantity", content)


class CheckStockTests(TestCase):
    def test_command_creates_alerts_and_reports(self):
        make_item(name="Low Thing", quantity=2, reorder_threshold=10)
        with tempfile.TemporaryDirectory() as tmp:
            call_command("check_stock", "--report-dir", tmp, "--quiet", "--no-exit")
            files = sorted(p.name for p in Path(tmp).iterdir())
            self.assertIn("latest_restock_report.txt", files)
            self.assertIn("latest_restock_report.csv", files)
            text = (Path(tmp) / "latest_restock_report.txt").read_text()
            self.assertIn("Low Thing", text)
        self.assertEqual(StockAlert.objects.count(), 1)

    def test_no_duplicates_same_day(self):
        make_item(quantity=0)
        call_command("check_stock", "--no-files", "--quiet", "--no-exit")
        call_command("check_stock", "--no-files", "--quiet", "--no-exit")
        self.assertEqual(StockAlert.objects.count(), 1)


class NLPIntentTests(TestCase):
    def test_classify_low_stock(self):
        intent, score = classify("which items are running low?")
        self.assertEqual(intent, "low_stock")
        self.assertGreater(score, 0)

    def test_classify_quantity(self):
        intent, _ = classify("how many staplers do we have?")
        self.assertEqual(intent, "quantity_query")

    def test_entity_extraction_fuzzy_item(self):
        make_item(name="A4 Copy Paper 80gsm")
        ent = extract_entities("how much a4 copy paper do we have")
        self.assertIsNotNone(ent.item)
        self.assertEqual(ent.item.name, "A4 Copy Paper 80gsm")

    def test_briefing_mentions_attention_when_low(self):
        make_item(quantity=0)
        text = morning_briefing()
        self.assertIn("need attention", text)
        self.assertIn("out of stock", text)


class RAGTests(TestCase):
    def test_retrieval_finds_relevant_item(self):
        make_item(name="Laser Toner HP 26A", supplier="PrintSupply Ltd")
        make_item(name="Coffee Beans 1kg", supplier="BrewCo")
        hits = retrieve("who supplies the laser toner", top_k=2)
        self.assertTrue(hits)
        self.assertEqual(hits[0][0].name, "Laser Toner HP 26A")

    def test_generated_answer_is_grounded(self):
        make_item(name="Laser Toner HP 26A", supplier="PrintSupply Ltd")
        result = answer_question("who supplies the laser toner and where is it stored?")
        self.assertIn("PrintSupply Ltd", result["answer"])
        self.assertEqual(result["intent"], "rag_retrieval")
        self.assertTrue(result["sources"])
        self.assertEqual(QueryLog.objects.count(), 1)


class AssistantFlowTests(TestCase):
    def test_low_stock_question_returns_table(self):
        make_item(name="Pens", quantity=4, reorder_threshold=40)
        result = answer_question("which items are running low?")
        self.assertIn("Pens", result["answer"])
        self.assertEqual(result["intent"], "low_stock")
        self.assertEqual(len(result["results"]), 1)

    def test_help_intent(self):
        result = answer_question("help")
        self.assertEqual(result["intent"], "help")


class ViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.item = make_item(name="View Item", quantity=3, reorder_threshold=10)

    def test_dashboard(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Morning briefing")
        self.assertContains(resp, "View Item")

    def test_item_list_filters(self):
        resp = self.client.get(reverse("item_list"), {"status": "LOW"})
        self.assertContains(resp, "View Item")
        resp = self.client.get(reverse("item_list"), {"status": "OK"})
        self.assertNotContains(resp, "View Item")

    def test_full_crud_cycle(self):
        # CREATE
        resp = self.client.post(
            reverse("item_create"),
            {
                "name": "Cycle Item", "sku": "", "category": "Test",
                "quantity": 5, "reorder_threshold": 8, "reorder_quantity": 0,
                "unit_price": "1.50", "supplier": "S", "location": "L",
                "notes": "", "is_active": "on",
            },
        )
        item = Item.objects.get(name="Cycle Item")
        self.assertRedirects(resp, reverse("item_detail", args=[item.pk]))
        # UPDATE
        resp = self.client.post(
            reverse("item_update", args=[item.pk]),
            {
                "name": "Cycle Item v2", "sku": item.sku, "category": "Test",
                "quantity": 8, "reorder_threshold": 8, "reorder_quantity": 0,
                "unit_price": "1.50", "supplier": "S", "location": "L",
                "notes": "", "is_active": "on",
            },
        )
        item.refresh_from_db()
        self.assertEqual(item.name, "Cycle Item v2")
        self.assertEqual(item.status, Item.Status.LOW)
        # DELETE
        resp = self.client.post(reverse("item_delete", args=[item.pk]))
        self.assertRedirects(resp, reverse("item_list"))
        self.assertFalse(Item.objects.filter(pk=item.pk).exists())

    def test_adjust_stock(self):
        resp = self.client.post(
            reverse("item_adjust", args=[self.item.pk]),
            {"delta": "-2", "reason": "SALE", "note": "sold 2"},
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 1)
        self.assertRedirects(resp, reverse("item_detail", args=[self.item.pk]))
        # cannot go below zero (view redirects back with a flash message)
        resp = self.client.post(
            reverse("item_adjust", args=[self.item.pk]),
            {"delta": "-50", "reason": "SALE", "note": ""},
            follow=True,
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 1)
        self.assertContains(resp, "cannot go below zero")

    def test_import_and_export_pages(self):
        csv_content = b"Item Name,Current Quantity,Reorder Threshold\nImported,5,9\n"
        resp = self.client.post(
            reverse("import_csv"),
            {"file": io.BytesIO(csv_content), "update_existing": "on"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Item.objects.filter(name="Imported").exists())
        resp = self.client.get(reverse("export_csv"))
        self.assertEqual(resp["Content-Type"].lower(), "text/csv; charset=utf-8")

    def test_assistant_page(self):
        resp = self.client.get(reverse("assistant"), {"q": "which items are running low?"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "intent")

    def test_reports_page_and_generate(self):
        resp = self.client.post(reverse("reports_generate"))
        self.assertRedirects(resp, reverse("reports"))
        resp = self.client.get(reverse("reports"))
        self.assertContains(resp, "latest_restock_report")

    def test_about_page(self):
        resp = self.client.get(reverse("about"))
        self.assertContains(resp, "RAG")
