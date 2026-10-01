"""Create fresh schemas; never migrate or replace an existing installation."""
from sqlalchemy import inspect, text
from database import Base
import models  # register tables

SCHEMA_VERSION = 200


def initialize_schema(engine):
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        if tables:
            if "schema_version" not in tables:
                raise RuntimeError("旧数据库结构不受支持。请保留备份，在新的安装目录初始化。")
            version = connection.execute(text("SELECT version FROM schema_version")).scalar()
            if version != SCHEMA_VERSION:
                raise RuntimeError("数据库结构版本不匹配，请使用对应版本程序或恢复备份。")
            return
        Base.metadata.create_all(connection)
        connection.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        connection.execute(text("INSERT INTO schema_version VALUES (:version)"), {"version": SCHEMA_VERSION})
        connection.execute(text("CREATE UNIQUE INDEX uq_member ON project_members(project_id,user_id)"))
        connection.execute(text("CREATE UNIQUE INDEX uq_signer ON signers(user_id,signer_type)"))
        connection.execute(text("""CREATE TRIGGER report_history_prevent_reuse
            BEFORE UPDATE OF report_no ON projects
            WHEN NEW.report_no IS NOT NULL AND (OLD.report_no IS NULL OR NEW.report_no != OLD.report_no)
            AND EXISTS (SELECT 1 FROM report_number_history WHERE report_no=NEW.report_no)
            BEGIN SELECT RAISE(ABORT, 'report number already issued'); END"""))
        connection.execute(text("""CREATE TRIGGER report_history_record_issue
            AFTER UPDATE OF report_no ON projects
            WHEN NEW.report_no IS NOT NULL AND (OLD.report_no IS NULL OR NEW.report_no != OLD.report_no)
            BEGIN INSERT INTO report_number_history(project_id,report_no,is_recycled,is_legacy)
            VALUES(NEW.id,NEW.report_no,0,0); END"""))
        connection.execute(text("""CREATE TRIGGER report_history_record_recycle
            AFTER UPDATE OF report_no_status,is_deleted ON projects
            WHEN NEW.report_no IS NOT NULL AND (NEW.report_no_status='recycled' OR NEW.is_deleted=1)
            BEGIN UPDATE report_number_history SET is_recycled=1,
            recycled_at=COALESCE(recycled_at,CURRENT_TIMESTAMP) WHERE report_no=NEW.report_no; END"""))
