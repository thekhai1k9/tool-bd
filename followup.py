"""Mẫu và kết quả tin nhắn riêng; không kết nối trình duyệt/Sheet."""
import datetime
import re


def now():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7))).isoformat(timespec="seconds")


def parse_templates(rows):
    if len(rows) < 3:
        raise ValueError("TIN NHẮN FOLLOW UP thiếu hàng SKU hoặc nội dung hàng 3")
    templates = {}
    for col, raw in enumerate(rows[1][1:], start=1):
        if not raw.strip():
            continue
        message = rows[2][col] if col < len(rows[2]) else ""
        for sku in raw.split(";"):
            sku = sku.strip()
            if not sku.isdigit():
                raise ValueError(f"SKU không hợp lệ ở TIN NHẮN FOLLOW UP: {sku!r}")
            if sku in templates and templates[sku] != message:
                raise ValueError(f"SKU {sku} có nhiều mẫu follow-up khác nhau")
            templates[sku] = message
    return templates


def render_message(template, creator):
    if not isinstance(template, str) or not template.strip():
        raise ValueError("Thiếu mẫu TIN NHẮN FOLLOW UP cho SKU")
    name = str(creator.get("name") or creator["username"]).strip()
    message = template.replace("{Tên Creator}", name)
    if re.search(r"\{[^{}]*\}", message):
        raise ValueError("Mẫu follow-up còn biến chưa thay")
    if len(message.encode("utf-16-le")) // 2 > 2000:
        raise ValueError("Tin nhắn follow-up vượt 2000 ký tự UTF-16 của khung chat")
    return message


def summarize(recipients):
    sent = [state for state in recipients.values() if state["status"] == "sent"]
    latest = max((state["sent_at"] for state in sent), default=None)
    day = datetime.datetime.fromisoformat(latest).strftime("%d/%m/%Y") if latest else ""
    return len(sent), day, [name for name, state in recipients.items() if state["status"] == "rate_limited"]
