"""Integer-cent financial aggregation; voids preserve original entries."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import func
import models


def cents(value):
    return int((Decimal(str(value or 0)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def refresh_project_finance(db, project):
    rows = db.query(models.FinancialEntry.kind, func.sum(models.FinancialEntry.amount_cents),
        func.max(models.FinancialEntry.occurred_on)).filter_by(project_id=project.id).filter(
        models.FinancialEntry.voided_at.is_(None)).group_by(models.FinancialEntry.kind).all()
    totals = {kind: (amount, occurred_on) for kind, amount, occurred_on in rows}
    invoices, invoice_date = totals.get('invoice', (0, None))
    receipts, receive_date = totals.get('receipt', (0, None))
    project.invoiced_amount_cents = invoices
    project.received_amount_cents = receipts
    project.invoice_date = datetime.combine(invoice_date, datetime.min.time()) if invoice_date else None
    project.receive_date = datetime.combine(receive_date, datetime.min.time()) if receive_date else None
