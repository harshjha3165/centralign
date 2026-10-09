"""Resets Ledger's DB and regenerates sandbox/invoices/*.pdf for one scenario.

Reads the `seed` block of tasks/<scenario_id>.yaml so every fixture (which
invoices exist, what they say, what's already in the DB) lives in the
scenario file, not in worker code.
"""
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from sandbox.ledger_app.db import get_conn

ROOT = Path(__file__).resolve().parent.parent
INVOICES_DIR = ROOT / "sandbox" / "invoices"
TASKS_DIR = ROOT / "tasks"


def _fmt_money(n):
    return f"${n:,.2f}"


def make_invoice_pdf(path, vendor, invoice_no, invoice_date, terms_days, subtotal, tax, advance_paid, footer):
    total = subtotal + tax
    amount_due = total - advance_paid
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, 740, vendor)
    c.setFont("Helvetica", 11)
    y = 710
    for line in [
        f"Invoice #{invoice_no}",
        f"Invoice Date: {invoice_date}",
        f"Terms: Net {terms_days}",
        "",
        f"Subtotal: {_fmt_money(subtotal)}",
        f"Tax: {_fmt_money(tax)}",
        f"Total: {_fmt_money(total)}",
        f"Advance Paid: {_fmt_money(advance_paid)}",
        f"Amount Due: {_fmt_money(amount_due)}",
    ]:
        c.drawString(72, y, line)
        y -= 20
    if footer:
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(72, 80, footer)
    c.save()


def reset_db(existing_bills):
    conn = get_conn()
    conn.execute("DROP TABLE IF EXISTS bills")
    conn.execute(
        """CREATE TABLE bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor TEXT NOT NULL,
            invoice_no TEXT NOT NULL,
            amount REAL NOT NULL,
            due_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL
        )"""
    )
    now = datetime.now(timezone.utc).isoformat()
    for b in existing_bills:
        conn.execute(
            "INSERT INTO bills (vendor, invoice_no, amount, due_date, status, created_at) VALUES (?,?,?,?,?,?)",
            (b["vendor"], b["invoice_no"], b["amount"], b["due_date"], b.get("status", "open"), now),
        )
    conn.commit()
    conn.close()


def main(scenario_id):
    spec = yaml.safe_load((TASKS_DIR / f"{scenario_id}.yaml").read_text())
    seed = spec.get("seed", {})

    if INVOICES_DIR.exists():
        shutil.rmtree(INVOICES_DIR)
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)

    for inv in seed.get("invoices", []):
        make_invoice_pdf(
            INVOICES_DIR / inv["filename"],
            inv["vendor"], inv["invoice_no"], inv["invoice_date"],
            inv.get("terms_days", 30), inv["subtotal"], inv["tax"],
            inv.get("advance_paid", 0.0), inv.get("footer", ""),
        )

    reset_db(seed.get("existing_bills", []))
    print(f"Seeded {scenario_id}: {len(seed.get('invoices', []))} invoice(s), "
          f"{len(seed.get('existing_bills', []))} existing bill(s).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m sandbox.seed <scenario_id>")
        sys.exit(1)
    main(sys.argv[1])
