"""Public error vocabulary; never return raw exception/SQL contents."""
import re
import traceback

DEFAULTS = {
    400: ("invalid_request", "请求内容或访问地址不正确，请检查后重试"),
    401: ("login_required", "登录已失效或账号密码不正确，请重新登录"),
    402: ("license_restricted", "当前授权限制此操作，请联系管理员"),
    403: ("permission_denied", "无权限执行此操作，请联系管理员确认权限"),
    404: ("not_found", "请求的记录或接口不存在，请刷新页面"),
    405: ("method_not_allowed", "此接口不支持当前操作，请刷新页面或联系管理员"),
    409: ("state_conflict", "记录状态已变化，请刷新后核对再操作"),
    413: ("request_too_large", "上传内容超过大小限制，请缩小文件后重试"),
    422: ("invalid_input", "输入格式或字段不合法，请检查必填项与格式"),
    429: ("rate_limited", "操作过于频繁或服务器正忙，请稍后重试"),
}

def category(status):
    if status >= 500: return "system_error"
    if status in (401, 403): return "access_restriction"
    if status == 429: return "rate_limit"
    if status >= 400: return "business_restriction"
    return "success"

def public_error(status, detail=None):
    code, fallback = DEFAULTS.get(status, ("internal_error", "服务处理失败，请联系管理员并提供请求编号") if status >= 500 else ("request_rejected", "请求未完成，请检查后重试"))
    message = detail.get("message") if isinstance(detail, dict) else detail
    candidate = detail.get("code") if isinstance(detail, dict) else None
    if isinstance(candidate, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", candidate): code = candidate
    # Only application-authored Chinese messages are public; 5xx always use a safe generic explanation.
    if status >= 500 or not isinstance(message, str) or not re.search(r"[\u4e00-\u9fff]", message): message = fallback
    return {"code": code, "message": message[:500], "category": category(status)}

def exception_location(error):
    # Frame names/line numbers help locate defects without serializing locals, source, or exception messages.
    return " > ".join(f"{frame.filename.replace(chr(92), '/').rsplit('/', 1)[-1]}:{frame.lineno}:{frame.name}"
                      for frame in traceback.extract_tb(error.__traceback__)[-6:])

FIELD_NAMES = {"username":"账号", "password":"密码", "admin_username":"管理员账号", "admin_password":"管理员密码",
               "reason":"原因", "expected_revision":"记录修订号", "customer_id":"客户", "name":"名称", "customer_code":"客户编号",
               "expires_at":"到期时间", "max_users":"执业人数上限", "max_instances":"实例数上限", "since":"开始时间", "until":"结束时间",
               "page":"页码", "actor_id":"操作用户ID", "request_id":"请求编号", "client_base_url":"客户端连接地址",
               "current_password":"原密码", "new_password":"新密码", "license_document":"授权文件", "tax_id":"税号"}

def validation_message(errors):
    hints = []
    for error in errors[:5]:
        kind = error.get("type", "")
        loc = error.get("loc", ())
        label = next((FIELD_NAMES[item] for item in reversed(loc) if item in FIELD_NAMES), "输入字段")
        if "missing" in kind: hint = label + "为必填项"
        elif "extra" in kind: hint = "包含当前接口不接受的字段，请刷新页面后重新填写"
        elif "json" in kind: hint = "提交内容不是有效的JSON格式"
        else: hint = label + "格式、长度或取值范围不正确"
        if hint not in hints: hints.append(hint)
    return "；".join(hints) or "输入格式或字段不合法，请检查必填项与格式"
