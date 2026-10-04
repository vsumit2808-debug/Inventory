from django import forms

from .models import Item, StockMovement


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = [
            "name", "sku", "category", "quantity", "reorder_threshold",
            "reorder_quantity", "unit_price", "supplier", "location",
            "notes", "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input"}),
            "sku": forms.TextInput(attrs={"class": "input", "placeholder": "Leave blank to auto-generate"}),
            "category": forms.TextInput(attrs={"class": "input"}),
            "quantity": forms.NumberInput(attrs={"class": "input", "min": "0"}),
            "reorder_threshold": forms.NumberInput(attrs={"class": "input", "min": "0"}),
            "reorder_quantity": forms.NumberInput(attrs={"class": "input", "min": "0"}),
            "unit_price": forms.NumberInput(attrs={"class": "input", "min": "0", "step": "0.01"}),
            "supplier": forms.TextInput(attrs={"class": "input"}),
            "location": forms.TextInput(attrs={"class": "input"}),
            "notes": forms.Textarea(attrs={"class": "input", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # SKU is optional on create (auto-generated) and shown read-only-ish
        self.fields["sku"].required = False


class AdjustStockForm(forms.Form):
    REASONS = [
        (StockMovement.Reason.PURCHASE, "Purchase received"),
        (StockMovement.Reason.SALE, "Sale / issued out"),
        (StockMovement.Reason.ADJUSTMENT, "Manual adjustment"),
        (StockMovement.Reason.RETURN, "Customer return"),
        (StockMovement.Reason.DAMAGE, "Damage / loss"),
    ]

    delta = forms.IntegerField(
        label="Quantity change",
        help_text="Positive to add stock, negative to remove (e.g. -3).",
        widget=forms.NumberInput(attrs={"class": "input", "step": "1"}),
    )
    reason = forms.ChoiceField(choices=REASONS, widget=forms.Select(attrs={"class": "input"}))
    note = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "Optional note"}),
    )


class ImportCSVForm(forms.Form):
    file = forms.FileField(
        label="Stock CSV file",
        widget=forms.FileInput(attrs={"class": "input"}),
        help_text="Columns like: Item Name, Current Quantity, Reorder Threshold "
        "(flexible aliases accepted).",
    )
    update_existing = forms.BooleanField(
        required=False,
        label="Update existing items when a duplicate is detected "
        "(by SKU or fuzzy name match)",
    )


class QuestionForm(forms.Form):
    question = forms.CharField(
        label="Ask about your stock",
        max_length=300,
        widget=forms.TextInput(
            attrs={
                "class": "input input-lg",
                "placeholder": "e.g. which items are running low?",
            }
        ),
    )
