"""Từ khóa mở rộng và checkpoint theo ngày/shop/SKU, không kết nối TikTok/Sheet."""
import datetime
import hashlib
import json
import re
import unicodedata
from pathlib import Path


# Chỉ dịch các cụm có nghĩa rõ ràng, không tự sinh brand hoặc đổi tiêu chí SKU.
BILINGUAL_TERMS = (
    ("thực phẩm bảo vệ sức khỏe", "dietary supplements"),
    ("thực phẩm chức năng", "supplements"),
    ("chăm sóc cá nhân", "personal care"),
    ("chăm sóc da", "skin care"),
    ("chăm sóc tóc", "hair care"),
    ("làm đẹp", "beauty"),
    ("mỹ phẩm", "cosmetics"),
    ("sức khỏe", "health"),
    ("thể thao", "sports"),
    ("ngoài trời", "outdoors"),
)


def build_search_terms(keywords, product, english_keywords=()):
    """Ưu tiên keyword VI, EN trên Sheet; brand và biến thể tự tạo tìm sau."""
    result, seen = [], set()

    def add(value):
        value = " ".join(str(value).split())
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            result.append(value)

    for keyword in keywords:
        add(keyword)
    for keyword in english_keywords:
        add(keyword)
    add(product)
    for keyword in list(result):
        plain = unicodedata.normalize("NFD", keyword.replace("đ", "d").replace("Đ", "D"))
        add("".join(c for c in plain if unicodedata.category(c) != "Mn"))
        for translations in (dict(BILINGUAL_TERMS), {en: vi for vi, en in BILINGUAL_TERMS}):
            phrases = sorted(translations, key=len, reverse=True)
            pattern = r"(?<!\w)(?:" + "|".join(re.escape(phrase) for phrase in phrases) + r")(?!\w)"
            add(re.sub(pattern, lambda match: translations[match.group().casefold()], keyword, flags=re.IGNORECASE))
    return result


class DailyProgress:
    def __init__(self, shop, sku_id, directory="outputs/checkpoints", day=None):
        day = day or datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=7))
        ).strftime("%Y-%m-%d")
        shop_key = hashlib.sha256(shop.strip().lower().encode("utf-8")).hexdigest()[:12]
        if not str(sku_id).isdigit():
            raise ValueError(f"SKU ID không hợp lệ: {sku_id!r}")
        self.path = Path(directory) / f"{day}_{shop_key}_{sku_id}.json"
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            if (self.data["day"], self.data["shop"], self.data["sku_id"]) != (day, shop, str(sku_id)):
                raise RuntimeError("Checkpoint không khớp ngày/shop/SKU")
        else:
            self.data = {
                "day": day, "shop": shop, "sku_id": str(sku_id),
                "selected": {}, "scanned": {}, "finished_keywords": [], "batches": [],
            }

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    @property
    def sent_usernames(self):
        return {
            username
            for batch in self.data["batches"]
            if batch["status"] in ("sent", "completed")
            for username in batch["usernames"]
        }

    @property
    def pending_usernames(self):
        return [name for name in self.data["selected"] if name not in self.sent_usernames]

    @property
    def has_unfinished_batch(self):
        return any(batch["status"] not in ("completed", "superseded") for batch in self.data["batches"])

    @property
    def blocking_batches(self):
        # sending cũ không được tự coi là draft: có thể TikTok đã nhận lệnh gửi.
        return [batch for batch in self.data["batches"] if batch["status"] not in (
            "draft", "ready", "completed", "superseded",
        )]

    def prepare_batches(self, target, batch_size=50):
        """Tái dùng đợt draft/ready, chỉ tạo đợt mới cho creator chưa được phân bổ."""
        if self.blocking_batches:
            raise RuntimeError("Có đợt đã thao tác gửi hoặc chưa rõ kết quả; không tự tạo lại.")
        remaining = self.pending_usernames[:max(0, target - len(self.sent_usernames))]
        available = set(remaining)
        jobs = []
        for batch in self.data["batches"]:
            if batch["status"] not in ("draft", "ready"):
                continue
            names = batch["usernames"]
            if names and len(names) == len(set(names)) and set(names) <= available:
                jobs.append(batch)
                available.difference_update(names)
            else:
                batch.update(status="superseded", error="Danh sách/tiêu chí/mục tiêu đã đổi; phân bổ lại người chưa gửi.")
        unassigned = [name for name in remaining if name in available]
        next_index = max((batch["index"] for batch in self.data["batches"]), default=0) + 1
        for offset in range(0, len(unassigned), batch_size):
            batch = {
                "index": next_index, "status": "draft", "stage": "configure_invitation", "attempt": 0,
                "usernames": unassigned[offset:offset + batch_size],
            }
            next_index += 1
            self.data["batches"].append(batch)
            jobs.append(batch)
        self.save()
        return jobs
