"""Create fresh schemas; never migrate or replace an existing installation."""
from sqlalchemy import inspect, text
from database import Base
import models  # register tables

SCHEMA_VERSION = 600


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
        connection.execute(text('INSERT INTO export_access_epoch(id,value) VALUES(1,1)'))
        # Conservatively invalidate generated files when identity or object scope changes.
        for table, actions in {
            'users':['UPDATE OF is_active,permission_revision,session_version'],
            'user_roles':['INSERT','UPDATE','DELETE'],
            'user_special_grants':['INSERT','UPDATE','DELETE'],
            'project_members':['INSERT','UPDATE','DELETE'],
            'projects':['UPDATE OF leader_id,signer1_id,signer2_id,customer_id,is_deleted'],
            'signers':['UPDATE OF user_id,is_active','DELETE'],
            'customers':['UPDATE OF merged_into_id'],
            'customer_billing_profiles':['UPDATE OF is_active']
        }.items():
            for index, action in enumerate(actions):
                connection.execute(text(f'CREATE TRIGGER export_epoch_{table}_{index} AFTER {action} ON {table} BEGIN UPDATE export_access_epoch SET value=value+1 WHERE id=1; END'))
        connection.execute(text('CREATE INDEX idx_project_dashboard ON projects(fiscal_year,is_deleted,project_status)'))
        connection.execute(text("CREATE UNIQUE INDEX uq_member ON project_members(project_id,user_id)"))
        connection.execute(text("CREATE UNIQUE INDEX uq_signer ON signers(user_id,signer_type)"))
        connection.execute(text("CREATE UNIQUE INDEX uq_billing_default ON customer_billing_profiles(customer_id) WHERE is_active=1 AND is_default=1"))
        connection.execute(text("""CREATE TRIGGER billing_pointer_belongs BEFORE UPDATE OF current_verified_version_id ON customer_billing_profiles
            WHEN NEW.current_verified_version_id IS NOT NULL AND NOT EXISTS
            (SELECT 1 FROM customer_billing_versions WHERE id=NEW.current_verified_version_id AND profile_id=NEW.id AND status='verified')
            BEGIN SELECT RAISE(ABORT, 'billing version does not belong to profile'); END"""))
        connection.execute(text("""CREATE TRIGGER verified_billing_immutable BEFORE UPDATE ON customer_billing_versions
            WHEN OLD.status IN ('verified','superseded') AND
            (NEW.public_json IS NOT OLD.public_json OR NEW.sensitive_ciphertext IS NOT OLD.sensitive_ciphertext
             OR NEW.profile_id IS NOT OLD.profile_id OR NEW.key_id IS NOT OLD.key_id OR NEW.bank_last4 IS NOT OLD.bank_last4
             OR NEW.version_no IS NOT OLD.version_no OR NEW.verified_by IS NOT OLD.verified_by OR NEW.verified_at IS NOT OLD.verified_at
             OR NEW.status NOT IN ('verified','superseded'))
            BEGIN SELECT RAISE(ABORT, 'verified billing payload is immutable'); END"""))
        for table in ('invoice_billing_snapshots', 'audit_events'):
            for action in ('UPDATE', 'DELETE'):
                connection.execute(text(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable record'); END"))
        connection.execute(text("""CREATE TRIGGER finance_no_delete BEFORE DELETE ON financial_entries
            BEGIN SELECT RAISE(ABORT, 'void financial records instead'); END"""))
        connection.execute(text("""CREATE TRIGGER verified_billing_no_delete BEFORE DELETE ON customer_billing_versions
            WHEN OLD.status IN ('verified','superseded')
            BEGIN SELECT RAISE(ABORT, 'verified billing record is immutable'); END"""))
        connection.execute(text("""CREATE TRIGGER finance_payload_immutable BEFORE UPDATE ON financial_entries
            WHEN NEW.project_id IS NOT OLD.project_id OR NEW.kind IS NOT OLD.kind
            OR NEW.amount_cents IS NOT OLD.amount_cents OR NEW.occurred_on IS NOT OLD.occurred_on
            OR NEW.reference IS NOT OLD.reference OR NEW.note IS NOT OLD.note
            OR NEW.created_by IS NOT OLD.created_by OR NEW.replacement_of_id IS NOT OLD.replacement_of_id
            OR (OLD.voided_at IS NOT NULL AND (NEW.voided_at IS NOT OLD.voided_at
              OR NEW.voided_by IS NOT OLD.voided_by OR NEW.void_reason IS NOT OLD.void_reason))
            BEGIN SELECT RAISE(ABORT, 'void financial records instead'); END"""))
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
