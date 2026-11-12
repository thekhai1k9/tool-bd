"""Pure creator rules; no Sheet or browser dependencies. Existing semantics preserved."""
import re


def normalize_username(username):
    return (username or "").strip().lstrip("@").lower()


def parse_compact_number(text):
    """'25,3K' / '1,2M' / '12,5Tr' / '300' -> int. None nếu không đọc được
    hoặc ô trống / gạch ngang (—, --, -) = không có dữ liệu."""
    if text is None:
        return None
    s = str(text).strip().lower().replace(" ", "")
    if not s:
        return None
    # Ô không có dữ liệu: chỉ chứa dấu gạch ngang
    if re.fullmatch(r"[-–—]+", s):
        return None

    m = re.search(r"(\d[\d.,]*)(k|m|b|tr|tỷ|ty)?", s)
    if not m:
        return None

    raw, unit = m.group(1), m.group(2)
    if unit:
        if "," in raw and "." not in raw:
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            return None
        mult = {"k": 10**3, "m": 10**6, "b": 10**9, "tr": 10**6, "tỷ": 10**9, "ty": 10**9}[unit]
        return int(val * mult)

    digits = re.sub(r"\D", "", raw)
    return int(digits) if digits else None


def parse_follower_rule(text):
    """'1000<Followers<30000' -> (1000, 30000). (None, None) nếu không có rule."""
    nums = [int(x) for x in re.findall(r"\d+", text or "")]
    if len(nums) >= 2:
        return nums[0], nums[1]
    if len(nums) == 1:
        return nums[0], 10**12
    return None, None


def parse_min_rule(text):
    """'>300 đơn / 30 ngày' -> 300. None nếu không có rule."""
    m = re.search(r"\d[\d.,]*", text or "")
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(0))
    return int(digits) if digits else None


def validate_creator(creator, sku):
    """Đối chiếu creator với tiêu chí SKU. Trả về (ok, [lý do loại]).
    Loại khi thiếu số liệu bắt buộc hoặc số liệu không đạt."""
    reasons = []

    fmin, fmax = parse_follower_rule(sku.get("followers_rule", ""))
    if fmin is not None:
        fv = parse_compact_number(creator.get("followers"))
        if fv is None:
            reasons.append("thiếu dữ liệu followers bắt buộc")
        elif not (fmin <= fv <= fmax):
            reasons.append(f"followers {fv} ngoài khoảng {fmin}-{fmax}")

    omin = parse_min_rule(sku.get("orders_rule", ""))
    if omin is not None:
        ov = parse_compact_number(creator.get("orders"))
        if ov is None:
            reasons.append("thiếu dữ liệu số món bắt buộc")
        elif ov <= omin:
            reasons.append(f"số món {ov} <= {omin}")

    gmin = parse_min_rule(sku.get("gmv_rule", ""))
    if gmin is not None:
        gv = parse_compact_number(creator.get("gmv"))
        if gv is None:
            reasons.append("thiếu dữ liệu GMV bắt buộc")
        elif gv <= gmin:
            reasons.append(f"GMV {gv} <= {gmin}")

    return (len(reasons) == 0), reasons
