"""Build a sample contract PDF with sig*/email_* AcroForm fields."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import black, white
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def write_field_contract(path: Path) -> Path:
    """Write a one-page contract with customer + company signature fields."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    form = c.acroForm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, height - 72, "Wallace Marina Contract")
    c.setFont("Helvetica", 11)
    c.drawString(72, height - 96, "Sample two-phase signature contract")

    def labeled_text(name: str, label: str, x: float, y: float, value: str = "", w: float = 220) -> None:
        c.setFont("Helvetica", 9)
        c.drawString(x, y + 22, label)
        form.textfield(
            name=name,
            tooltip=label,
            x=x,
            y=y,
            width=w,
            height=18,
            borderWidth=1,
            borderColor=black,
            fillColor=white,
            textColor=black,
            forceBorder=True,
            fontSize=10,
            value=value,
        )

    def sig_box(name: str, label: str, x: float, y: float) -> None:
        c.setFont("Helvetica", 9)
        c.drawString(x, y + 58, label)
        form.textfield(
            name=name,
            tooltip=label,
            x=x,
            y=y,
            width=200,
            height=50,
            borderWidth=1,
            borderColor=black,
            fillColor=white,
            textColor=black,
            forceBorder=True,
            fontSize=10,
            value="",
        )

    labeled_text("email_sig1", "Owner email (email_sig1)", 72, height - 150, "alice@example.com")
    labeled_text("name_sig1", "Owner name (name_sig1)", 320, height - 150, "Alice Owner", w=180)
    labeled_text("email_sig2", "Co-owner email (email_sig2)", 72, height - 210, "bob@example.com")
    labeled_text("name_sig2", "Co-owner name (name_sig2)", 320, height - 210, "Bob CoOwner", w=180)
    labeled_text(
        "email_companysig1",
        "Marina email (email_companysig1)",
        72,
        height - 270,
        "office@wallace1.com",
        w=260,
    )
    labeled_text(
        "name_companysig1",
        "Marina name (name_companysig1)",
        360,
        height - 270,
        "Marina Owner",
        w=160,
    )

    sig_box("sig1", "Owner signature (sig1)", 72, 220)
    sig_box("sig2", "Co-owner signature (sig2)", 320, 220)
    sig_box("companysig1", "Marina signature (companysig1)", 72, 120)

    c.save()
    return path


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "sample_field_contract.pdf"
    write_field_contract(out)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
