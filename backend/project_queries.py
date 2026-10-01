"""Filters shared by project lists and exports."""
from sqlalchemy import or_
import models


def filter_projects(query, filters):
    p=models.Project
    query=query.filter(p.is_deleted==False,p.fiscal_year==filters['fiscal_year'])
    for field in ('firm','report_type','project_status','leader_id','report_year','customer_id'):
        value=filters.get(field)
        if value is not None:
            query=query.filter(getattr(p,field)==value)
    if filters.get('search'):
        search='%'+filters['search']+'%'
        query=query.filter(or_(p.project_id.ilike(search),p.customer_name.ilike(search),
                              p.customer_tax_id.ilike(search),p.report_no.ilike(search)))
    return query
