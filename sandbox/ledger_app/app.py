"""Ledger: a deliberately small, deliberately boring mock internal AP system.

FAULT and UI_VARIANT are read once at process start, which is why
tests/run_scenarios.py launches one fresh server subprocess per scenario
instead of reusing a long-lived process.
"""
import os
import re
import time
from datetime import datetime, timezone

from flask import Flask, abort, redirect, render_template, request, session, url_for

from .db import get_conn

FAULT = os.environ.get("FAULT", "none")
UI_VARIANT = os.environ.get("UI_VARIANT", "a")

VENDORS = ["Northwind Traders", "Northwind Trading Co", "Acme Supplies", "Globex Corp", "Initech"]

app = Flask(__name__)
app.secret_key = "ledger-sandbox-dev-key"

# Fault triggers fire once per server lifetime so a retry succeeds.
_state = {"fake_success_fired": False, "fault_500_fired": False}


@app.before_request
def _maybe_slow():
    if FAULT == "slow_load":
        time.sleep(2.5)


def _parse_amount(raw):
    cleaned = raw.strip().replace("$", "").replace(",", "")
    return float(cleaned)


def _validate_bill_form(form):
    errors = {}
    vendor = form.get("vendor", "")
    invoice_no = form.get("invoice_no", "").strip()
    amount_raw = form.get("amount", "").strip()
    due_date = form.get("due_date", "").strip()

    if vendor not in VENDORS:
        errors["vendor"] = "Choose a vendor from the list."
    if not invoice_no:
        errors["invoice_no"] = "Invoice number is required."
    amount = None
    if not amount_raw:
        errors["amount"] = "Amount is required."
    else:
        try:
            amount = _parse_amount(amount_raw)
        except ValueError:
            errors["amount"] = "Enter a plain number, e.g. 124500.00."
    if not due_date:
        errors["due_date"] = "Due date is required."
    elif not re.match(r"^\d{4}-\d{2}-\d{2}$", due_date):
        errors["due_date"] = "Due date must be in YYYY-MM-DD format."

    return errors, {"vendor": vendor, "invoice_no": invoice_no, "amount": amount_raw, "due_date": due_date}, amount


@app.route("/")
def list_bills():
    q = request.args.get("q", "").strip().lower()
    conn = get_conn()
    rows = conn.execute("SELECT * FROM bills ORDER BY id").fetchall()
    conn.close()
    if q:
        rows = [r for r in rows if q in r["vendor"].lower() or q in r["invoice_no"].lower()]
    show_survey = not session.get("survey_seen")
    return render_template(
        "list.html", bills=rows, q=request.args.get("q", ""), show_survey=show_survey,
        saved=request.args.get("saved") == "1",
    )


@app.route("/survey/close", methods=["POST"])
def dismiss_survey():
    session["survey_seen"] = True
    return redirect(url_for("list_bills"))


@app.route("/bills/new", methods=["GET", "POST"])
def new_bill():
    show_survey = not session.get("survey_seen")
    if request.method == "GET":
        template = "form_b.html" if UI_VARIANT == "b" else "form.html"
        return render_template(template, vendors=VENDORS, values={}, errors={}, show_survey=show_survey)

    errors, values, amount = _validate_bill_form(request.form)
    template = "form_b.html" if UI_VARIANT == "b" else "form.html"
    if errors:
        return render_template(template, vendors=VENDORS, values=values, errors=errors, show_survey=show_survey)

    if FAULT == "fake_success" and not _state["fake_success_fired"]:
        _state["fake_success_fired"] = True
        return redirect(url_for("list_bills", saved=1))

    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO bills (vendor, invoice_no, amount, due_date, status, created_at) VALUES (?,?,?,?,?,?)",
        (values["vendor"], values["invoice_no"], amount, values["due_date"], "open",
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()

    if FAULT == "submit_500_after_save" and not _state["fault_500_fired"]:
        _state["fault_500_fired"] = True
        return render_template("error.html"), 500

    return redirect(url_for("bill_detail", bill_id=new_id, saved=1))


@app.route("/bills/<int:bill_id>")
def bill_detail(bill_id):
    conn = get_conn()
    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    conn.close()
    if bill is None:
        abort(404)
    show_survey = not session.get("survey_seen")
    return render_template(
        "detail.html", bill=bill, show_survey=show_survey, saved=request.args.get("saved") == "1",
    )


@app.route("/bills/<int:bill_id>/delete", methods=["POST"])
def delete_bill(bill_id):
    conn = get_conn()
    conn.execute("DELETE FROM bills WHERE id = ?", (bill_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("list_bills"))


@app.route("/bills/<int:bill_id>/paid", methods=["POST"])
def mark_paid(bill_id):
    conn = get_conn()
    conn.execute("UPDATE bills SET status = 'paid' WHERE id = ?", (bill_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("bill_detail", bill_id=bill_id))


if __name__ == "__main__":
    app.run(host="localhost", port=8000, debug=False)
