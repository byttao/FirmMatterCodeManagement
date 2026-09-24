"""
报告编号生成器
- 唯一数据源：fiscal_years -> fiscal_year_firms -> fiscal_year_report_types -> report_number_rules
- 不使用旧版 fiscal_year_configs 表，不使用 report_sequences 表，不使用默认模板
- 如果对应的年度/事务所/业务类型 在新表中未配置，直接报错（不静默降级）

模板格式说明：
- {yyyy} - 四位年份，如 2026
- {yy}   - 两位年份，如 26
- {nnn}  - 编号，n 的个数决定位数，如 {nnn}=001, {nnnn}=0001
"""
from sqlalchemy.orm import Session
from sqlalchemy import update
import re
import models


def get_rule(db: Session, firm: str, report_type: str, year: int) -> "models.ReportNumberRule":
    """
    从三级结构获取编号规则。
    找不到时直接抛出 ValueError，不降级到旧表或默认模板。
    """
    fy = db.query(models.FiscalYear).filter(models.FiscalYear.year == year).first()
    if not fy:
        raise ValueError(f"编号年度 {year} 未配置，请先在「编号年度配置」中添加该年度")

    fy_firm = db.query(models.FiscalYearFirm).filter(
        models.FiscalYearFirm.fiscal_year_id == fy.id,
        models.FiscalYearFirm.firm == firm
    ).first()
    if not fy_firm:
        raise ValueError(f"事务所「{firm}」在 {year} 年度未配置，请先在「编号年度配置」中添加")

    rt = db.query(models.FiscalYearReportType).filter(
        models.FiscalYearReportType.fiscal_year_firm_id == fy_firm.id,
        models.FiscalYearReportType.report_type == report_type
    ).first()
    if not rt:
        raise ValueError(f"业务类型「{report_type}」在 {year}/{firm} 下未配置，请先在「编号年度配置」中添加")

    rule = db.query(models.ReportNumberRule).filter(
        models.ReportNumberRule.id == rt.rule_id,
        models.ReportNumberRule.is_active == True
    ).first()
    if not rule:
        raise ValueError(f"业务类型「{report_type}」关联的编号规则不存在或已停用")

    return rule


def parse_sequence_pattern(template: str) -> int:
    """从模板中解析编号位数"""
    match = re.search(r'\{(n+)\}', template)
    if match:
        return len(match.group(1))
    return 3  # 默认3位


def generate_report_no(db: Session, firm: str, report_type: str, year: int) -> str:
    """生成报告编号；由调用方与项目状态一起提交。"""
    rule = get_rule(db, firm, report_type, year)

    current_seq = db.execute(
        update(models.ReportNumberRule)
        .where(models.ReportNumberRule.id == rule.id)
        .values(current_sequence=models.ReportNumberRule.current_sequence + 1)
        .returning(models.ReportNumberRule.current_sequence)
    ).scalar_one()

    seq_str = str(current_seq).zfill(rule.sequence_digits)

    report_no = rule.template
    report_no = report_no.replace('{yyyy}', str(year))
    report_no = report_no.replace('{yy}', str(year)[-2:])
    report_no = re.sub(r'\{n+\}', seq_str, report_no)

    return report_no


def recycle_report_no(db: Session, project: "models.Project") -> None:
    """回收编号时保留原编号以供查阅，序列保持单调递增。"""
    if not project or not project.report_no:
        return
    project.report_no_status = models.ReportStatus.RECYCLED.value


def get_available_report_years(db: Session) -> list:
    """
    获取可选的报告年份列表——从新三级结构读取已配置年度
    """
    years = db.query(models.FiscalYear.year).order_by(
        models.FiscalYear.year.desc()
    ).all()
    return [y[0] for y in years]


def get_available_firms(db: Session, year: int) -> list:
    """获取指定年度已配置的事务所列表"""
    fy = db.query(models.FiscalYear).filter(models.FiscalYear.year == year).first()
    if not fy:
        return []
    firms = db.query(models.FiscalYearFirm.firm).filter(
        models.FiscalYearFirm.fiscal_year_id == fy.id
    ).all()
    return [f[0] for f in firms]


def get_available_report_types(db: Session, firm: str, year: int) -> list:
    """获取指定年度+事务所已配置的业务类型列表"""
    fy = db.query(models.FiscalYear).filter(models.FiscalYear.year == year).first()
    if not fy:
        return []
    fy_firm = db.query(models.FiscalYearFirm).filter(
        models.FiscalYearFirm.fiscal_year_id == fy.id,
        models.FiscalYearFirm.firm == firm
    ).first()
    if not fy_firm:
        return []
    rts = db.query(models.FiscalYearReportType.report_type).filter(
        models.FiscalYearReportType.fiscal_year_firm_id == fy_firm.id
    ).all()
    return [r[0] for r in rts]


def preview_report_no(firm: str, report_type: str, year: int, template: str) -> str:
    """预览报告编号示例（不增加序号，需要调用方传入 template）"""
    sequence_digits = parse_sequence_pattern(template)
    seq_str = '1'.zfill(sequence_digits)

    preview = template
    preview = preview.replace('{yyyy}', str(year))
    preview = preview.replace('{yy}', str(year)[-2:])
    preview = re.sub(r'\{n+\}', seq_str, preview)

    return preview
