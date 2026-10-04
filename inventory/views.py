"""
All HTTP views: dashboard, item CRUD, stock adjustments, CSV import/export,
report centre and the NLP/RAG assistant. Plain Django - no front-end JS.
"""
import csv
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.db.models import Sum
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import AdjustStockForm, ImportCSVForm, ItemForm, QuestionForm
from .models import Item, QueryLog, StockAlert, StockMovement
from .nlp.assistant import answer_question
from .nlp.summary import morning_briefing
from .services.csvio import export_csv, import_rows
from .services.stock import build_restock_report, evaluate_rows, iter_item_dicts


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def dashboard(request):
    items = list(Item.objects.filter(is_active=True))
    rows, stats = evaluate_rows(iter_item_dicts(items))
    restock = sorted(rows, key=lambda r: (r["severity"] != "OUT", r["name"]))
    stock_value = sum(float(i.stock_value) for i in items)

    categories = {}
    for i in items:
        categories[i.category or "General"] = (
            categories.get(i.category or "General", 0) + i.quantity
        )
    max_cat = max(categories.values()) if categories else 0
    chart = [
        {
            "label": label,
            "total": total,
            "pct": int(round(total / max_cat * 100)) if max_cat else 0,
        }
        for label, total in sorted(categories.items(), key=lambda kv: -kv[1])
    ]

    context = {
        "stats": stats,
        "stock_value": stock_value,
        "restock": restock,
        "briefing": morning_briefing(items),
        "chart": chart,
        "recent_movements": StockMovement.objects.select_related("item")[:8],
        "recent_alerts": StockAlert.objects.all()[:5],
        "total_units": sum(i.quantity for i in items),
    }
    return render(request, "inventory/dashboard.html", context)


# ---------------------------------------------------------------------------
# Item CRUD
# ---------------------------------------------------------------------------
def item_list(request):
    items = list(Item.objects.filter(is_active=True))
    q = (request.GET.get("q") or "").strip()
    category = (request.GET.get("category") or "").strip()
    status = (request.GET.get("status") or "").strip()

    if q:
        ql = q.lower()
        items = [
            i
            for i in items
            if ql in i.name.lower() or ql in i.sku.lower() or ql in i.supplier.lower()
        ]
    if category:
        items = [i for i in items if (i.category or "General") == category]
    if status:
        items = [i for i in items if i.status == status]

    categories = sorted({(i.category or "General") for i in Item.objects.filter(is_active=True)})
    return render(
        request,
        "inventory/item_list.html",
        {
            "items": items,
            "q": q,
            "category": category,
            "status": status,
            "categories": categories,
        },
    )


def item_detail(request, pk):
    item = get_object_or_404(Item, pk=pk)
    return render(
        request,
        "inventory/item_detail.html",
        {
            "item": item,
            "movements": item.movements.all()[:20],
            "alerts": item.alerts.all()[:10],
            "adjust_form": AdjustStockForm(),
        },
    )


def item_create(request):
    form = ItemForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.save()
        StockMovement.objects.create(
            item=item,
            delta=item.quantity,
            reason=StockMovement.Reason.INITIAL,
            note="Created via web form",
        )
        messages.success(request, "Item '%s' created." % item.name)
        return redirect("item_detail", pk=item.pk)
    return render(
        request, "inventory/item_form.html", {"form": form, "title": "Add item"}
    )


def item_update(request, pk):
    item = get_object_or_404(Item, pk=pk)
    form = ItemForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        old_qty = item.quantity
        item = form.save()
        if item.quantity != old_qty:
            StockMovement.objects.create(
                item=item,
                delta=item.quantity - old_qty,
                reason=StockMovement.Reason.ADJUSTMENT,
                note="Quantity changed via item edit",
            )
        messages.success(request, "Item '%s' updated." % item.name)
        return redirect("item_detail", pk=item.pk)
    return render(
        request,
        "inventory/item_form.html",
        {"form": form, "title": "Edit: %s" % item.name, "item": item},
    )


@require_POST
def item_delete(request, pk):
    item = get_object_or_404(Item, pk=pk)
    name = item.name
    item.delete()
    messages.success(request, "Item '%s' deleted." % name)
    return redirect("item_list")


def item_confirm_delete(request, pk):
    item = get_object_or_404(Item, pk=pk)
    return render(request, "inventory/item_confirm_delete.html", {"item": item})


def item_adjust(request, pk):
    """Record a stock in/out movement with a reason (audit-trailed)."""
    item = get_object_or_404(Item, pk=pk)
    form = AdjustStockForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        delta = form.cleaned_data["delta"]
        new_qty = item.quantity + delta
        if new_qty < 0:
            messages.error(
                request,
                "Adjustment rejected: stock cannot go below zero (current %d, change %+d)."
                % (item.quantity, delta),
            )
            return redirect("item_detail", pk=item.pk)
        item.quantity = new_qty
        item.save()
        StockMovement.objects.create(
            item=item,
            delta=delta,
            reason=form.cleaned_data["reason"],
            note=form.cleaned_data["note"],
        )
        messages.success(request, "Stock adjusted: %s %+d." % (item.name, delta))
        return redirect("item_detail", pk=item.pk)
    return render(
        request,
        "inventory/adjust_stock.html",
        {"form": form, "item": item},
    )


# ---------------------------------------------------------------------------
# CSV import / export
# ---------------------------------------------------------------------------
def import_csv(request):
    result = None
    form = ImportCSVForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        text = request.FILES["file"].read().decode("utf-8-sig")
        sample, body = text[:4096], text
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(body.splitlines(), dialect=dialect)
        result = import_rows(
            reader, update_existing=form.cleaned_data["update_existing"]
        )
        messages.success(
            request,
            "CSV processed: %d created, %d updated, %d skipped."
            % (len(result["created"]), len(result["updated"]), len(result["skipped"])),
        )
    return render(
        request, "inventory/import_csv.html", {"form": form, "result": result}
    )


def export_csv_view(request):
    content = export_csv()
    response = HttpResponse(content, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="stock_export.csv"'
    return response


# ---------------------------------------------------------------------------
# Report centre
# ---------------------------------------------------------------------------
def reports(request):
    report_dir = Path(settings.REPORT_DIR)
    files = []
    if report_dir.exists():
        for f in sorted(report_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if f.suffix in (".txt", ".csv") and f.is_file():
                files.append(
                    {
                        "name": f.name,
                        "size_kb": f.stat().st_size / 1024,
                        "mtime": f.stat().st_mtime,
                    }
                )
    return render(
        request,
        "inventory/reports.html",
        {"files": files, "alerts": StockAlert.objects.all()[:30]},
    )


@require_POST
def reports_generate(request):
    report = build_restock_report()
    messages.success(
        request,
        "Report generated: %d item(s) flagged (%d out of stock)."
        % (len(report["rows"]), report["stats"]["out"]),
    )
    return redirect("reports")


def report_download(request, name):
    """Serve a generated report file (basename-checked, extension-allowed)."""
    safe = Path(name).name
    if not safe.endswith((".txt", ".csv")):
        messages.error(request, "Invalid file type.")
        return redirect("reports")
    path = Path(settings.REPORT_DIR) / safe
    if not path.exists():
        messages.error(request, "Report '%s' not found." % safe)
        return redirect("reports")
    return FileResponse(path.open("rb"), as_attachment=True, filename=safe)


# ---------------------------------------------------------------------------
# NLP / RAG assistant
# ---------------------------------------------------------------------------
def assistant(request):
    question = (request.GET.get("q") or "").strip()
    result = None
    if question:
        result = answer_question(question)
    recent = QueryLog.objects.all()[:8]
    return render(
        request,
        "inventory/assistant.html",
        {"form": QuestionForm(initial={"question": question}) if question else QuestionForm(),
         "question": question,
         "result": result,
         "recent": recent},
    )


# ---------------------------------------------------------------------------
# "How the AI works" explainer (client-facing)
# ---------------------------------------------------------------------------
def about(request):
    return render(request, "inventory/about.html")
