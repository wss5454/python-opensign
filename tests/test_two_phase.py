"""Tests for PDF form-field parsing and two-phase signing gates."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Realtime-monitor"))

from app.services import (  # noqa: E402
    _signers_to_email,
    active_phase,
    apply_widgets_to_pdf,
    assign_ordered_widgets,
    can_signer_act,
)
from pdf_fields import PdfFieldError, extract_signers_from_pdf  # noqa: E402
from scripts.make_field_contract import write_field_contract  # noqa: E402


def _signer(**kwargs):
    data = {
        "id": kwargs.get("id", 1),
        "role": "signer",
        "status": "pending",
        "phase": 0,
        "order_index": 0,
        "name": "S",
        "email": "s@example.com",
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _doc(*signers, sequential=False, status="sent"):
    return SimpleNamespace(signers=list(signers), sequential=sequential, status=status)


class PdfFieldParseTests(unittest.TestCase):
    def test_extracts_customer_and_company_signers(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = write_field_contract(Path(tmp) / "contract.pdf")
            signers = extract_signers_from_pdf(pdf)

        self.assertEqual(len(signers), 3)
        by_field = {s["field_name"]: s for s in signers}

        self.assertEqual(by_field["sig1"]["email"], "alice@example.com")
        self.assertEqual(by_field["sig1"]["name"], "Alice Owner")
        self.assertEqual(by_field["sig1"]["phase"], 0)
        self.assertEqual(by_field["sig1"]["order_index"], 0)
        self.assertEqual(by_field["sig1"]["widgets"][0]["field_name"], "sig1")
        self.assertGreater(by_field["sig1"]["widgets"][0]["w"], 1)
        self.assertGreater(by_field["sig1"]["widgets"][0]["h"], 1)

        self.assertEqual(by_field["sig2"]["email"], "bob@example.com")
        self.assertEqual(by_field["sig2"]["phase"], 0)
        self.assertEqual(by_field["sig2"]["order_index"], 1)

        self.assertEqual(by_field["companysig1"]["email"], "office@wallace1.com")
        self.assertEqual(by_field["companysig1"]["phase"], 1)
        self.assertEqual(by_field["companysig1"]["order_index"], 0)

        # Signature boxes should not all collapse onto the same auto-grid cell.
        boxes = [(s["widgets"][0]["x"], s["widgets"][0]["y"]) for s in signers]
        self.assertEqual(len(set(boxes)), 3)

    def test_missing_email_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "bad.pdf"
            write_field_contract(pdf_path)
            # Rebuild without email_sig1 by generating then we simulate via a
            # contract that has sig1 but no matching email field.
            from reportlab.lib.colors import black, white
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas

            c = canvas.Canvas(str(pdf_path), pagesize=letter)
            form = c.acroForm
            form.textfield(
                name="sig1",
                x=72,
                y=200,
                width=200,
                height=50,
                borderWidth=1,
                borderColor=black,
                fillColor=white,
                forceBorder=True,
                value="",
            )
            c.save()
            with self.assertRaises(PdfFieldError) as ctx:
                extract_signers_from_pdf(pdf_path)
            self.assertIn("email_sig1", str(ctx.exception))

    def test_client_contract_filled(self):
        pdf = ROOT / "Contract_filled.pdf"
        if not pdf.is_file():
            self.skipTest("Contract_filled.pdf not present")
        signers = extract_signers_from_pdf(pdf)
        by_field = {s["field_name"]: s for s in signers}
        self.assertEqual(len(signers), 3)
        self.assertEqual(by_field["sig1"]["email"], "wsslogin@gmail.com")
        self.assertEqual(by_field["sig1"]["name"], "Test Customer")
        self.assertEqual(by_field["sig2"]["email"], "wsslogin@gmail.com")
        self.assertEqual(by_field["sig2"]["name"], "Susie Customer")
        self.assertEqual(by_field["companysig1"]["email"], "jaclyn@wallace1.com")
        self.assertEqual(by_field["companysig1"]["name"], "Robert Smith")
        self.assertEqual(by_field["companysig1"]["phase"], 1)

    def test_client_contract_not_filled_raises(self):
        pdf = ROOT / "Contract_not_filled.pdf"
        if not pdf.is_file():
            self.skipTest("Contract_not_filled.pdf not present")
        with self.assertRaises(PdfFieldError):
            extract_signers_from_pdf(pdf)


class WidgetAnchorTests(unittest.TestCase):
    def test_field_named_widgets_are_not_relocated(self):
        overlapping = {
            "type": "signature",
            "page": 1,
            "x": 10.0,
            "y": 10.0,
            "w": 20.0,
            "h": 8.0,
            "field_name": "sig1",
        }
        other = dict(overlapping, field_name="sig2")
        signers = [
            {"name": "A", "email": "a@example.com", "order_index": 0, "widgets": [overlapping]},
            {"name": "B", "email": "b@example.com", "order_index": 1, "widgets": [other]},
        ]
        result = assign_ordered_widgets(signers)
        self.assertEqual(result[0]["widgets"][0]["x"], 10.0)
        self.assertEqual(result[0]["widgets"][0]["y"], 10.0)
        self.assertEqual(result[1]["widgets"][0]["x"], 10.0)
        self.assertEqual(result[1]["widgets"][0]["y"], 10.0)
        self.assertEqual(result[0]["widgets"][0]["field_name"], "sig1")


class PhaseGateTests(unittest.TestCase):
    def test_company_blocked_until_customers_sign(self):
        customer = _signer(id=1, phase=0, status="pending")
        company = _signer(id=2, phase=1, status="pending")
        doc = _doc(customer, company)
        self.assertEqual(active_phase(doc), 0)
        self.assertTrue(can_signer_act(doc, customer))
        self.assertFalse(can_signer_act(doc, company))

        to_email = _signers_to_email(doc)
        self.assertEqual([s.id for s in to_email], [1])

        customer.status = "signed"
        self.assertEqual(active_phase(doc), 1)
        self.assertTrue(can_signer_act(doc, company))
        self.assertEqual([s.id for s in _signers_to_email(doc)], [2])

    def test_all_customers_emailed_in_parallel(self):
        a = _signer(id=1, phase=0, order_index=0)
        b = _signer(id=2, phase=0, order_index=1)
        company = _signer(id=3, phase=1)
        doc = _doc(a, b, company, sequential=False)
        ids = [s.id for s in _signers_to_email(doc)]
        self.assertEqual(ids, [1, 2])

    def test_sequential_within_phase(self):
        a = _signer(id=1, phase=0, order_index=0)
        b = _signer(id=2, phase=0, order_index=1)
        company = _signer(id=3, phase=1)
        doc = _doc(a, b, company, sequential=True)
        ids = [s.id for s in _signers_to_email(doc)]
        self.assertEqual(ids, [1])
        a.status = "signed"
        self.assertEqual([s.id for s in _signers_to_email(doc)], [2])
        self.assertFalse(can_signer_act(doc, company))


class StampPreservesFormFieldsTests(unittest.TestCase):
    def test_filled_contract_keeps_name_and_address(self):
        pdf = ROOT / "Contract_filled.pdf"
        if not pdf.is_file():
            self.skipTest("Contract_filled.pdf not present")

        from pypdf import PdfReader
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sig_path = tmp_path / "sig.png"
            Image.new("RGBA", (200, 80), (0, 0, 0, 128)).save(sig_path)
            widget = SimpleNamespace(
                id=1,
                type="signature",
                page=1,
                x=10.0,
                y=80.0,
                w=20.0,
                h=8.0,
            )
            out_path = tmp_path / "stamped.pdf"
            apply_widgets_to_pdf(
                pdf,
                [widget],
                {1: sig_path},
                "Test Customer",
                out_path,
            )

            before = PdfReader(str(pdf)).get_fields() or {}
            after = PdfReader(str(out_path)).get_fields() or {}
            self.assertGreaterEqual(len(after), 30)

            def _val(fields, name):
                data = fields.get(name) or fields.get(f"/{name}")
                if not data:
                    return ""
                if isinstance(data, dict):
                    return str(data.get("/V") or "")
                return str(getattr(data, "value", "") or "")

            self.assertEqual(_val(after, "cName"), _val(before, "cName"))
            self.assertEqual(_val(after, "cAddress"), _val(before, "cAddress"))
            self.assertIn("TEST CUSTOMER", _val(after, "cName"))
            self.assertIn("123 ADDRESS", _val(after, "cAddress"))


if __name__ == "__main__":
    unittest.main()
