"""Plain work-order PDFs: signature box above the label, labeled email."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Realtime-monitor"))

from app.mail import signature_request_copy  # noqa: E402
from app.mail import _jinja  # noqa: E402
from pdf_anchor import (  # noqa: E402
    BOX_GAP_ABOVE,
    BOX_HEIGHT,
    BOX_LEFT_SHIFT,
    BOX_WIDTH,
    DEFAULT_FALLBACK_BOX,
    LABEL_ASCENT,
    extract_work_order_signers,
    find_anchor_box,
)
from pdf_emails import extract_emails_from_pdf  # noqa: E402
from pdf_fields import PdfFieldError, extract_signers_from_pdf  # noqa: E402

LABEL_X = 2.88
LABEL_BASELINE = 87.6
LABEL_FONT = 6.0


def _write(path: Path, draw) -> None:
    pdf = canvas.Canvas(str(path), pagesize=letter)
    draw(pdf)
    pdf.save()


def _expected_box() -> dict:
    """Widget percents for a label drawn at LABEL_X, LABEL_BASELINE."""
    label_top = LABEL_BASELINE + LABEL_FONT * LABEL_ASCENT
    bottom = label_top + BOX_GAP_ABOVE
    top = bottom + BOX_HEIGHT
    left = LABEL_X - BOX_LEFT_SHIFT
    right = left + BOX_WIDTH
    page_w, page_h = letter
    return {
        "x": round(left / page_w * 100.0, 2),
        "y": round((page_h - top) / page_h * 100.0, 2),
        "w": round((right - left) / page_w * 100.0, 2),
        "h": round((top - bottom) / page_h * 100.0, 2),
    }


class WorkOrderAnchorTests(unittest.TestCase):
    def test_places_box_above_label_and_reads_labeled_email(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "work-order.pdf"

            def draw(pdf_canvas):
                pdf_canvas.setFont("Times-Roman", 10)
                pdf_canvas.drawString(36, 720, "Email: Tom@Example.com")
                pdf_canvas.drawString(36, 700, "Shop admin@pier-pressure.com")
                pdf_canvas.showPage()
                pdf_canvas.setFont("Times-Roman", LABEL_FONT)
                pdf_canvas.drawString(LABEL_X, LABEL_BASELINE, "Customer Signature")

            _write(pdf, draw)

            self.assertEqual(extract_signers_from_pdf(pdf), [])
            signers = extract_work_order_signers(pdf)

        self.assertEqual(len(signers), 1)
        signer = signers[0]
        self.assertEqual(signer["email"], "tom@example.com")
        self.assertEqual(signer["name"], "tom")
        self.assertEqual(signer["role"], "signer")
        self.assertEqual(signer["phase"], 0)
        self.assertEqual(signer["order_index"], 0)
        self.assertEqual(signer["field_name"], "sig1")
        self.assertEqual(signer["widgets"], [{
            "type": "signature",
            "page": 2,
            "field_name": "sig1",
            **_expected_box(),
        }])
        self.assertNotEqual(signer["email"], "admin@pier-pressure.com")

    def test_split_label_and_extra_spaces_still_match(self):
        expected = _expected_box()
        with tempfile.TemporaryDirectory() as tmp:
            spaced = Path(tmp) / "spaced.pdf"
            split = Path(tmp) / "split.pdf"

            def draw_spaced(pdf_canvas):
                pdf_canvas.setFont("Times-Roman", LABEL_FONT)
                pdf_canvas.drawString(LABEL_X, LABEL_BASELINE, "Customer   Signature")
                pdf_canvas.setFont("Times-Roman", 10)
                pdf_canvas.drawString(36, 720, "E-mail: pat@example.com")

            def draw_split(pdf_canvas):
                pdf_canvas.setFont("Times-Roman", LABEL_FONT)
                pdf_canvas.drawString(LABEL_X, LABEL_BASELINE, "Customer")
                pdf_canvas.drawString(48, LABEL_BASELINE, "Signature")
                pdf_canvas.setFont("Times-Roman", 10)
                pdf_canvas.drawString(36, 720, "Email: pat@example.com")

            _write(spaced, draw_spaced)
            _write(split, draw_split)
            spaced_box = find_anchor_box(spaced)
            split_box = find_anchor_box(split)

        self.assertEqual(spaced_box["x"], expected["x"])
        self.assertEqual(spaced_box["y"], expected["y"])
        self.assertEqual(split_box["x"], expected["x"])
        self.assertEqual(split_box["page"], 1)

    def test_missing_labeled_email_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "no-email.pdf"

            def draw(pdf_canvas):
                pdf_canvas.setFont("Times-Roman", LABEL_FONT)
                pdf_canvas.drawString(LABEL_X, LABEL_BASELINE, "Customer Signature")
                pdf_canvas.setFont("Times-Roman", 10)
                pdf_canvas.drawString(36, 700, "admin@pier-pressure.com")

            _write(pdf, draw)
            with self.assertRaises(PdfFieldError) as caught:
                extract_work_order_signers(pdf)

        self.assertIn("Email:", str(caught.exception))
        self.assertIn("no-email.pdf", str(caught.exception))

    def test_without_anchor_leaves_legacy_email_scrape(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "notes.pdf"

            def draw(pdf_canvas):
                pdf_canvas.setFont("Times-Roman", 12)
                pdf_canvas.drawString(72, 700, "Please contact sam@example.com")

            _write(pdf, draw)
            signers = extract_work_order_signers(pdf)
            emails = extract_emails_from_pdf(pdf)

        self.assertEqual(signers, [])
        self.assertEqual(emails, ["sam@example.com"])

    def test_fallback_box_when_label_text_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "no-label.pdf"

            def draw(pdf_canvas):
                pdf_canvas.setFont("Times-Roman", 10)
                pdf_canvas.drawString(36, 720, "Email: ada@example.com")
                pdf_canvas.showPage()
                pdf_canvas.drawString(36, 700, "Page two")

            _write(pdf, draw)
            signers = extract_work_order_signers(pdf)
            skipped = extract_work_order_signers(pdf, {"fallback_box": False})

        self.assertEqual(len(signers), 1)
        self.assertEqual(signers[0]["email"], "ada@example.com")
        widget = signers[0]["widgets"][0]
        self.assertEqual(widget["page"], 2)
        self.assertEqual(widget["x"], DEFAULT_FALLBACK_BOX["x"])
        self.assertEqual(widget["y"], DEFAULT_FALLBACK_BOX["y"])
        self.assertEqual(widget["w"], DEFAULT_FALLBACK_BOX["w"])
        self.assertEqual(widget["h"], DEFAULT_FALLBACK_BOX["h"])
        self.assertEqual(skipped, [])


class WorkOrderMailTests(unittest.TestCase):
    def test_work_order_wording_replaces_contract_wording(self):
        copy = signature_request_copy(
            signer_name="tom",
            sign_url="https://sign.example/sign/abc",
            dealership_name="Pier Pressure",
            document_kind="work_order",
        )
        self.assertEqual(copy["subject"], "Your work order is ready for approval")
        self.assertIn(
            "Your work order from Pier Pressure is ready for approval",
            copy["intro"],
        )
        self.assertNotIn("reservation", copy["text_body"])

        html = _jinja.get_template("signature_request.html").render(
            customer_first_name=copy["customer_first_name"],
            dealership_name=copy["dealership_name"],
            sign_url=copy["sign_url"],
            is_work_order=copy["is_work_order"],
            preheader=copy["preheader"],
            questions=copy["questions"],
        )
        self.assertIn("ready for approval", html)
        self.assertNotIn("reservation", html)
        self.assertIn("this work order", html)

        contract = signature_request_copy(
            signer_name="Ada Owner",
            sign_url="https://sign.example/sign/abc",
            dealership_name="Bayview",
        )
        self.assertEqual(contract["subject"], "Your contract is ready for signature")
        self.assertIn("Your contract for Bayview", contract["intro"])
        self.assertIn("reservation", contract["text_body"])
