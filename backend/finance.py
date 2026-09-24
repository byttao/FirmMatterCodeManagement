"""Financial ledger migration and project balance projection."""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import text
from sqlalchemy.orm import Session

import models
from database import SessionLocal


def cents(value) -> int:
    return int((Decimal(str(value or 0)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def refresh_project_finance(db: Session, project: models.Project) -> None:
    entries = db.query(models.FinancialEntry).filter_by(project_id=project.id).all()
    invoices = [entry for entry in entries if entry.kind == "invoice"]
    receipts = [entry for entry in entries if entry.kind == "receipt"]
    invoice_cents = sum(entry.amount_cents for entry in invoices)
    receipt_cents = sum(entry.amount_cents for entry in receipts)
    project.invoiced_amount = invoice_cents / 100
    project.received_amount = receipt_cents / 100
    project.invoice_date = max((entry.occurred_on for entry in invoices if entry.occurred_on), default=None)
    project.receive_date = max((entry.occurred_on for entry in receipts if entry.occurred_on), default=None)
    project.uninvoiced_amount = (cents(project.contract_amount) - invoice_cents) / 100
    project.unreceived_amount = (invoice_cents - receipt_cents) / 100


def migrate_legacy_finance() -> None:
    """Import each project's old totals once, including projects with zero balances."""
    with SessionLocal() as db:
        if db.get_bind().dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))
        projects = db.query(models.Project).filter(
            ~models.Project.id.in_(db.query(models.FinanceMigration.project_id))
        ).all()
        for project in projects:
            for kind, amount, old_date in (
                ("invoice", project.invoiced_amount, project.invoice_date),
                ("receipt", project.received_amount, project.receive_date),
            ):
                amount_cents = cents(amount)
                if amount_cents > 0:
                    db.add(models.FinancialEntry(
                        project_id=project.id, kind=kind, amount_cents=amount_cents,
                        occurred_on=old_date.date() if isinstance(old_date, datetime) else old_date,
                        note="旧版汇总数据", is_legacy=True,
                    ))
            db.add(models.FinanceMigration(project_id=project.id))
            db.flush()
            refresh_project_finance(db, project)
        db.commit()
