"""Versioned, transactional SQLite upgrades for installed databases."""

from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

import models
from database import Base
from finance import migrate_legacy_finance


def migrate_signer_accounts(engine: Engine) -> None:
    with engine.begin() as connection:
        _migrate_signer_accounts(connection)


def _migrate_signer_accounts(connection: Connection) -> None:
    if "user_id" not in {column["name"] for column in inspect(connection).get_columns("signers")}:
        connection.execute(text("ALTER TABLE signers ADD COLUMN user_id INTEGER REFERENCES users(id)"))
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_signers_user_firm "
        "ON signers (user_id, signer_type)"
    ))


def backfill_report_number_history(connection: Connection) -> None:
    with Session(connection) as db:
        existing = {number for (number,) in db.query(models.ReportNumberHistory.report_no).all()}
        for project in db.query(models.Project).filter(models.Project.report_no.isnot(None)):
            if project.report_no not in existing:
                db.add(models.ReportNumberHistory(
                    project_id=project.id,
                    report_no=project.report_no,
                    is_recycled=(project.report_no_status == models.ReportStatus.RECYCLED.value or project.is_deleted),
                    is_legacy=True,
                ))
                existing.add(project.report_no)
        db.flush()

    connection.execute(text("""
        CREATE TRIGGER IF NOT EXISTS report_history_prevent_reuse
        BEFORE UPDATE OF report_no ON projects
        WHEN NEW.report_no IS NOT NULL
            AND (OLD.report_no IS NULL OR NEW.report_no != OLD.report_no)
            AND EXISTS (SELECT 1 FROM report_number_history WHERE report_no = NEW.report_no)
        BEGIN
            SELECT RAISE(ABORT, 'report number already issued');
        END
    """))
    connection.execute(text("""
        CREATE TRIGGER IF NOT EXISTS report_history_record_issue
        AFTER UPDATE OF report_no ON projects
        WHEN NEW.report_no IS NOT NULL
            AND (OLD.report_no IS NULL OR NEW.report_no != OLD.report_no)
        BEGIN
            INSERT INTO report_number_history (project_id, report_no, is_recycled, is_legacy)
            VALUES (NEW.id, NEW.report_no, 0, 0);
        END
    """))
    connection.execute(text("""
        CREATE TRIGGER IF NOT EXISTS report_history_record_recycle
        AFTER UPDATE OF report_no_status, is_deleted ON projects
        WHEN NEW.report_no IS NOT NULL
            AND (NEW.report_no_status = 'recycled' OR NEW.is_deleted = 1)
        BEGIN
            UPDATE report_number_history
            SET is_recycled = 1, recycled_at = COALESCE(recycled_at, CURRENT_TIMESTAMP)
            WHERE report_no = NEW.report_no;
        END
    """))


def _create_schema(connection: Connection) -> None:
    Base.metadata.create_all(bind=connection)


def _migrate_finance(connection: Connection) -> None:
    with Session(connection) as db:
        migrate_legacy_finance(db)
        db.flush()


MIGRATIONS = (
    (1, _create_schema),
    (2, _migrate_signer_accounts),
    (3, _migrate_finance),
    (4, backfill_report_number_history),
)


def _backup_database(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = path.with_name(f"{path.stem}-before-upgrade-{stamp}{path.suffix}")
    try:
        with sqlite3.connect(path) as source, sqlite3.connect(backup) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("升级前数据库备份完整性检查失败")
        os.chmod(backup, 0o600)
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    return backup


def upgrade_database(engine: Engine) -> Path | None:
    """Upgrade before serving requests; leave a restorable backup for existing data."""
    if engine.dialect.name != "sqlite":
        raise RuntimeError("自动升级目前仅支持 SQLite 数据库")

    database_path = engine.url.database
    if not database_path or database_path == ":memory:":
        raise RuntimeError("自动升级需要文件形式的 SQLite 数据库")
    path = Path(database_path)

    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        if "schema_migrations" in tables:
            applied = {row[0] for row in connection.execute(text("SELECT version FROM schema_migrations"))}
        else:
            applied = set()
        known = {version for version, _ in MIGRATIONS}
        if applied - known or applied != set(range(1, max(applied, default=0) + 1)):
            raise RuntimeError(f"数据库版本记录无法识别：{sorted(applied)}；请使用匹配的程序版本")
        pending = [(version, action) for version, action in MIGRATIONS if version not in applied]
        if not pending:
            return None

    backup = _backup_database(path) if tables - {"schema_migrations"} else None
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                connection.execute(text("""
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                applied = {row[0] for row in connection.execute(text("SELECT version FROM schema_migrations"))}
                for version, action in MIGRATIONS:
                    if version not in applied:
                        action(connection)
                        connection.execute(text(
                            "INSERT INTO schema_migrations (version) VALUES (:version)"
                        ), {"version": version})
                connection.commit()
            except Exception:
                connection.rollback()
                raise
    except Exception as exc:
        location = f"；升级前备份：{backup}" if backup else ""
        raise RuntimeError(f"数据库升级失败，服务未启动{location}") from exc
    return backup
