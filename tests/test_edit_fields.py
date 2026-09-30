"""Customer number prefixes and edit1/edit2 form fields."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
from pypdf import PdfReader
from reportlab.lib.colors import black, white
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pdf_form import list_edit_fields, normalize_edit_values  # noqa: E402
from app.services import (  # noqa: E402
    apply_widgets_to_pdf,
    customer_number_from_filename,
    prefixed_attachment_name,
)


def _write_contract(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    form = c.acroForm
    form.textfield(
        name="cName",
        x=72,
        y=700,
        width=200,
        height=18,
        borderWidth=1,
        borderColor=black,
        fillColor=white,
        textColor=black,
        forceBorder=True,
        value="KEEP ME",
    )
    form.textfield(
        name="edit1",
        x=72,
        y=640,
        width=220,
        height=18,
        borderWidth=1,
        borderColor=black,
        fillColor=white,
        textColor=black,
        forceBorder=True,
        value="",
    )
    form.textfield(
        name="edit2",
        x=72,
        y=600,
        width=220,
        height=18,
        borderWidth=1,
        borderColor=black,
        fillColor=white,
        textColor=black,
        forceBorder=True,
        value="already",
    )
    form.textfield(
        name="sig1",
        x=72,
        y=500,
        width=180,
        height=40,
        borderWidth=1,
        borderColor=black,
        fillColor=white,
        textColor=black,
        forceBorder=True,
        value="",
    )
    c.save()


def _field_value(fields: dict, name: str) -> str:
    data = fields.get(name) or fields.get(f"/{name}")
    if not data:
        return ""
    if isinstance(data, dict):
        return str(data.get("/V") or "")
    return str(getattr(data, "value", "") or "")


class CustomerNumberTests(unittest.TestCase):
    def test_first_twelve_digits_skip_separator(self):
        self.assertEqual(
            customer_number_from_filename("00508661111_160908113014WET.pdf"),
            "005086611111",
        )

    def test_fewer_digits_uses_what_is_there(self):
        self.assertEqual(customer_number_from_filename("contract-42.pdf"), "42")
        self.assertEqual(customer_number_from_filename("notes.pdf"), "")

    def test_prefix_upload_name(self):
        self.assertEqual(
            prefixed_attachment_name(
                "00508661111_160908113014WET.pdf",
                "insurance card.JPG",
            ),
            "005086611111_insurance card.JPG",
        )

    def test_does_not_double_prefix(self):
        self.assertEqual(
            prefixed_attachment_name(
                "00508661111_160908113014WET.pdf",
                "005086611111_card.jpg",
            ),
            "005086611111_card.jpg",
        )

    def test_no_digits_leaves_name(self):
        self.assertEqual(
            prefixed_attachment_name("contract.pdf", r"..\photos\card.jpg"),
            "card.jpg",
        )


class EditFieldTests(unittest.TestCase):
    def test_lists_only_edit_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "contract.pdf"
            _write_contract(pdf)
            fields = list_edit_fields(pdf)
        names = [item["name"] for item in fields]
        self.assertEqual(names, ["edit1", "edit2"])
        self.assertEqual(fields[0]["page"], 1)
        self.assertGreater(fields[0]["w"], 1)
        self.assertEqual(fields[1]["value"], "already")

    def test_normalize_ignores_other_names(self):
        cleaned = normalize_edit_values(
            [
                {"name": "edit1", "value": "Policy 99"},
                {"name": "cName", "value": "nope"},
                {"name": "edit2", "value": "x" * 600},
            ]
        )
        self.assertEqual(cleaned["edit1"], "Policy 99")
        self.assertNotIn("cname", cleaned)
        self.assertEqual(len(cleaned["edit2"]), 500)

    def test_stamp_writes_edit_field_and_keeps_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf = tmp_path / "contract.pdf"
            _write_contract(pdf)
            sig_path = tmp_path / "sig.png"
            Image.new("RGBA", (200, 80), (0, 0, 0, 128)).save(sig_path)
            widget = SimpleNamespace(
                id=1,
                type="signature",
                page=1,
                x=10.0,
                y=70.0,
                w=20.0,
                h=8.0,
            )
            out_path = tmp_path / "stamped.pdf"
            apply_widgets_to_pdf(
                pdf,
                [widget],
                {1: sig_path},
                "Customer",
                out_path,
                field_values={"edit1": "Policy 99", "cName": "CHANGED"},
            )
            fields = PdfReader(str(out_path)).get_fields() or {}
            self.assertEqual(_field_value(fields, "edit1"), "Policy 99")
            self.assertEqual(_field_value(fields, "edit2"), "already")
            self.assertEqual(_field_value(fields, "cName"), "KEEP ME")


if __name__ == "__main__":
    unittest.main()
