"""Fixed action templates and shared SQL/object scope checks."""
from fastapi import HTTPException
from sqlalchemy import or_, false
import models

ROLE_PERMISSIONS = {
    "office_admin": {
        "project.read.all_basic", "project.create.assign", "project.edit.all_basic",
        "project.transfer", "project.delete.all", "project.export.all", "number.issue.all",
        "number.void", "number.configure", "signer.manage", "signer.delete",
        "customer.lookup", "customer.read.all", "customer.manage", "customer.merge",
        "customer.correct", "customer.propose", "billing.read.all", "billing.manage",
        "billing.verify", "billing.export_sensitive", "finance.read.all", "finance.write",
        "finance.void", "contract.write.all", "identity.manage", "license.manage",
        "system.backup", "audit.read",
    },
    "number_manager": {
        "project.read.all_basic", "project.create.assign", "project.edit.all_basic",
        "project.transfer", "project.delete.all", "project.export.all", "number.issue.all",
        "number.void", "number.configure", "signer.manage", "customer.lookup",
    },
    "finance": {
        "project.read.finance", "project.export.finance", "finance.read.all", "finance.write",
        "finance.void", "contract.write.all", "customer.lookup", "customer.read.all",
        "customer.manage", "customer.propose", "billing.read.all", "billing.manage", "billing.verify",
    },
    "practitioner": {
        "project.read.related", "project.create.self", "project.edit.led", "project.delete.led",
        "number.issue.led", "customer.lookup", "customer.read.related", "customer.propose.led",
        "billing.read.led", "billing.propose.led", "finance.summary.led", "contract.write.led",
    },
    "clerk": {"customer.lookup", "customer.propose"},
}
SPECIAL_GRANTS = {"project.export.related", "billing.export_sensitive"}


def effective_permissions(user):
    return set().union(*(ROLE_PERMISSIONS.get(role, set()) for role in user.roles),
                       set(user.special_grants) & SPECIAL_GRANTS)


def has(user, action):
    return action in effective_permissions(user)


def require(user, action):
    if not has(user, action):
        raise HTTPException(403, "无权限执行此操作")


def related_clause(user):
    return or_(models.Project.leader_id == user.id,
               models.Project.members.any(models.ProjectMember.user_id == user.id),
               models.Project.signer1.has(models.Signer.user_id == user.id),
               models.Project.signer2.has(models.Signer.user_id == user.id))


def project_scope(query, user, exporting=False):
    all_actions = ("project.export.all", "project.export.finance") if exporting else ("project.read.all_basic", "project.read.finance")
    if any(has(user, action) for action in all_actions):
        return query
    related_action = "project.export.related" if exporting else "project.read.related"
    return query.filter(related_clause(user) if has(user, related_action) else false())


def is_related(user, project):
    return (project.leader_id == user.id or any(m.user_id == user.id for m in project.members)
            or any(s and s.user_id == user.id for s in (project.signer1, project.signer2)))


def can_read_money(user, project):
    return has(user, "finance.read.all") or (has(user, "finance.summary.led") and project.leader_id == user.id)


def can_read_customer(user, customer, db, billing=False):
    if has(user, "billing.read.all" if billing else "customer.read.all"):
        return True
    action = "billing.read.led" if billing else "customer.read.related"
    if not has(user, action):
        return False
    query = db.query(models.Project.id).filter_by(customer_id=customer.id, is_deleted=False)
    return query.filter(models.Project.leader_id == user.id if billing else related_clause(user)).first() is not None


def project_response(project, user):
    from schemas import ProjectResponse
    result = ProjectResponse.from_orm(project)
    if not can_read_money(user, project):
        for field in ("contract_amount", "invoiced_amount", "received_amount", "uninvoiced_amount", "unreceived_amount", "invoice_date", "receive_date"):
            setattr(result, field, None)
    return result
