import os
import re
import time
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from urllib.parse import urlparse, parse_qs

# Trang "Tìm nhà sáng tạo" (copy đúng URL từ thanh địa chỉ khi bạn đang ở trang đó)
SEARCH_PAGE_URL = "https://affiliate.tiktok.com/affiliate/creator"

SEARCH_SEL = 'input[data-tid="m4b_input_search"]'
CREATOR_ROW_SEL = '[class*="wrapper-row__StyledTr"]'

# Từ khóa nhận diện cột trong bảng kết quả
COLUMN_KEYWORDS = {
    "creator":         ["nhà sáng tạo", "creator"],
    "gmv":             ["gmv", "doanh thu"],
    "orders":          ["số món", "bán ra", "đơn hàng", "đơn"],
    "videos":          ["video", "số video"],
    "avg_views":       ["lượt xem video trung bình", "lượt xem", "views"],
    "engagement_rate": ["tỷ lệ tương tác", "tương tác", "engagement"],
}

# Khớp "29,2K, Nữ 45%, 35-44" hoặc "1,2M, Nam ..." -> lấy "29,2K"
FOLLOWER_RE = re.compile(r"(\d[\d.,]*\s*[KkMm]?)\s*,\s*(?:Nữ|Nam)")


class TikTokBrowserAutomation:
    def __init__(self, user_data_dir="./user_data"):
        self.user_data_dir = user_data_dir
        self.playwright = None
        self.browser_context = None
        self.page = None

    # ------------------------------------------------------------------ #
    # Khởi động / đăng nhập
    # ------------------------------------------------------------------ #
    def start_browser(self):
        """Khởi động trình duyệt và mở thẳng trang tìm nhà sáng tạo"""
        os.makedirs(self.user_data_dir, exist_ok=True)
        self.playwright = sync_playwright().start()

        self.browser_context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.page = self.browser_context.pages[0] if self.browser_context.pages else self.browser_context.new_page()
        print("Đang mở trang tìm nhà sáng tạo...")
        self.page.goto(SEARCH_PAGE_URL)

    def wait_for_user_login(self):
        """Dừng chờ người dùng đăng nhập thủ công lần đầu"""
        print("\n" + "=" * 50)
        input(">>> HÃY ĐĂNG NHẬP TÀI KHOẢN TRÊN TRÌNH DUYỆT.\n"
              ">>> SAU KHI ĐĂNG NHẬP XONG VÀ VÀO ĐÚNG TRANG TÌM NHÀ SÁNG TẠO, BẤM ENTER...")
        print("=" * 50 + "\n")
        time.sleep(3)

    def close(self):
        """Đóng trình duyệt"""
        if self.browser_context:
            self.browser_context.close()
        if self.playwright:
            self.playwright.stop()

    # ------------------------------------------------------------------ #
    # Tiện ích frame / phần tử
    # ------------------------------------------------------------------ #
    def _active_frame(self):
        """Trả về frame chứa bảng kết quả (ưu tiên frame có ô tìm kiếm)"""
        for frame in self.page.frames:
            try:
                if frame.locator(SEARCH_SEL).count() > 0:
                    return frame
            except Exception:
                continue
        return self.page

    def find_search_input(self, timeout=20):
        """Tìm ô tìm kiếm ở trang chính hoặc trong iframe"""
        end = time.time() + timeout
        while time.time() < end:
            for frame in self.page.frames:
                loc = frame.locator(SEARCH_SEL)
                try:
                    if loc.count() > 0 and loc.first.is_visible():
                        return loc.first
                except Exception:
                    continue
            time.sleep(0.5)
        raise RuntimeError(
            f"Không thấy ô tìm kiếm. URL hiện tại: {self.page.url}\n"
            f"Số frame: {len(self.page.frames)}"
        )

    def click_visible(self, text, timeout=10000, force=False):
        """Bấm phần tử hiển thị khớp text, bỏ qua phần tử nằm trong bảng (th/td).
        force=True để click bỏ qua lớp overlay đang che (vd dropdown mở)."""
        end = time.time() + timeout / 1000
        while time.time() < end:
            loc = self.page.get_by_text(text, exact=True)
            for i in range(loc.count()):
                el = loc.nth(i)
                in_table = el.evaluate("e => !!e.closest('th, td')")
                if el.is_visible() and not in_table:
                    el.click(force=force)
                    time.sleep(1)
                    return
            time.sleep(0.5)
        raise RuntimeError(f"Không thấy phần tử hiển thị có text: '{text}'")

    def close_dropdown(self):
        """Đóng dropdown/menu đang mở bằng cách nhấn Escape và click vùng trống."""
        try:
            self.page.keyboard.press("Escape")
            time.sleep(0.4)

            self.page.mouse.click(10, 10)
            time.sleep(0.3)
        except Exception:
            pass

    def open_tab(self, tab_name):
        """Chuyển tab bộ lọc: 'Nhà sáng tạo', 'Người theo dõi' hoặc 'Hiệu suất'.
        Đóng dropdown cũ trước rồi click với force để không bị che."""
        self.close_dropdown()
        self.click_visible(tab_name, force=True)

    # ------------------------------------------------------------------ #
    # Bộ lọc
    # ------------------------------------------------------------------ #
    def reset_filters(self):
        """Bấm Đặt lại nếu đang bật. Nếu nút disabled (không có bộ lọc nào) thì bỏ qua."""
        try:
            self.page.get_by_text("Đặt lại", exact=True).first.click(timeout=3000)
            self.page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
        except PWTimeout:
            print("   -> Nút Đặt lại đang tắt, không có bộ lọc nào cần xóa.")
        except Exception as e:
            print(f"   -> Bỏ qua Đặt lại: {e}")

    def _tick_option_by_text(self, text, timeout=10):
        """Tìm phần tử chứa text (bỏ phần "(số)" cuối) và tích checkbox cạnh nó.
        Trả về True nếu đã tick (hoặc đã tick sẵn), False nếu không thấy."""
        end = time.time() + timeout
        while time.time() < end:
            candidates = self.page.get_by_text(text, exact=False)
            for i in range(candidates.count()):
                el = candidates.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    txt = re.sub(r"\s*\(\d+\)\s*$", "", el.inner_text().strip()).lower()
                    if text.strip().lower() not in txt:
                        continue

                    # Lấy container (label / item row) chứa text này
                    container = el.evaluate_handle(
                        "e => e.closest('label') || e.closest('[class*=\"item\"]') || e.closest('[role=\"option\"]') || e.parentElement"
                    ).as_element()
                    if container is None:
                        continue

                    # Tìm checkbox trong container
                    cb = container.query_selector('input[type="checkbox"]')
                    if cb is not None:
                        if not cb.is_checked():
                            cb.check()
                            time.sleep(0.5)
                        return True

                    # Không có input[type=checkbox]: thử click chính container (thường là label)
                    container.click()
                    time.sleep(0.5)
                    return True
                except Exception:
                    continue
            time.sleep(0.5)
        return False

    def apply_category_filter(self, category_name):
        """Lọc theo 1 hạng mục sản phẩm: mở dropdown, tìm text, tích checkbox cạnh nó.
        Trả về True nếu chọn được, False nếu bỏ qua."""
        try:
            self.close_dropdown()
            self.open_tab("Nhà sáng tạo")
            self.click_visible("Hạng mục sản phẩm", force=True)
            time.sleep(1)

            search = self.page.get_by_placeholder("Search")
            filled = False
            for i in range(search.count()):
                if search.nth(i).is_visible():
                    search.nth(i).fill(category_name)
                    filled = True
                    break
            if not filled:
                print(f"   ⚠ Không thấy ô tìm kiếm hạng mục, bỏ qua '{category_name}'.")
                self.page.keyboard.press("Escape")
                return False
            time.sleep(1.5)

            ok = self._tick_option_by_text(category_name)
            if not ok:
                print(f"   ⚠ Không thấy hạng mục khớp '{category_name}', bỏ qua.")
                self.page.keyboard.press("Escape")
                return False

            print(f"   ✓ Đã tick hạng mục: {category_name}")
            time.sleep(1)
            self.page.keyboard.press("Escape")
            time.sleep(1)
            return True
        except Exception as e:
            print(f"   ⚠ Lỗi khi lọc hạng mục '{category_name}': {e}")
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    def apply_follower_filter(self, min_followers=1000, max_followers=30000):
        """Lọc theo khoảng người theo dõi trong tab 'Người theo dõi'.
        Tìm các khoảng có sẵn trên UI và tick những khoảng giao với [min, max].
        Trả về True nếu tick được ít nhất 1 khoảng."""
        try:
            self.close_dropdown()
            self.open_tab("Người theo dõi")
            time.sleep(1)

            # Lấy tất cả text trong tab hiện tại để nhận diện các khoảng follower
            # Các label phổ biến: "1.000 - 10.000", "10.000 - 30.000", "Dưới 1.000", "Trên 30.000"...
            range_re = re.compile(
                r"(\d[\d.,]*)\s*[-–]\s*(\d[\d.,]*)"
                r"|(dưới|nhỏ hơn|under|less than)\s*(\d[\d.,]*)"
                r"|(trên|lớn hơn|hơn|over|more than)\s*(\d[\d.,]*)",
                re.IGNORECASE,
            )

            def parse_num(s):
                if not s:
                    return None
                s = s.replace(",", "").replace(".", "")
                digits = re.sub(r"\D", "", s)
                return int(digits) if digits else None

            # Tìm tất cả các element có khả năng là option (label chứa text có số)
            options = self.page.locator('label, [class*="item"], [role="option"]').all()
            ticked = 0
            for opt in options:
                try:
                    if not opt.is_visible():
                        continue
                    txt = opt.inner_text().strip()
                    m = range_re.search(txt)
                    if not m:
                        continue

                    lo, hi = None, None
                    if m.group(1) and m.group(2):
                        lo, hi = parse_num(m.group(1)), parse_num(m.group(2))
                    elif m.group(3) and m.group(4):
                        hi = parse_num(m.group(4))
                        lo = 0
                    elif m.group(5) and m.group(6):
                        lo = parse_num(m.group(6))
                        hi = 10**12

                    # Chỉ tick nếu khoảng này giao với [min_followers, max_followers]
                    if lo is not None and hi is not None and lo <= max_followers and hi >= min_followers:
                        cb = opt.query_selector('input[type="checkbox"]')
                        if cb is not None:
                            if not cb.is_checked():
                                cb.check()
                                time.sleep(0.3)
                        else:
                            opt.click()
                            time.sleep(0.3)
                        ticked += 1
                        print(f"   ✓ Tick khoảng follower: {txt}")
                except Exception:
                    continue

            if ticked == 0:
                print(f"   ⚠ Không nhận diện được khoảng follower nào, bỏ qua lọc follower.")
                return False

            time.sleep(1)
            return True
        except Exception as e:
            print(f"   ⚠ Lỗi khi lọc follower: {e}")
            return False

    # ------------------------------------------------------------------ #
    # Tìm kiếm / thu thập creator
    # ------------------------------------------------------------------ #
    def search_keyword(self, keyword):
        """Nhập từ khóa, chờ kết quả. Trả về (frame, locator_rows) hoặc (None, None)."""
        frame = self._active_frame()
        box = self.find_search_input()
        box.click()
        box.fill("")
        box.type(keyword, delay=50)
        box.press("Enter")

        rows = frame.locator(CREATOR_ROW_SEL)
        try:
            rows.first.wait_for(state="visible", timeout=15000)
        except PWTimeout:
            return None, None
        time.sleep(2)
        return frame, rows

    def _scroll_to_load(self, frame, rows, max_rows, rounds):
        """Scroll liên tục để tải thêm kết quả cho tới khi đủ hoặc hết"""
        last_count = -1
        for _ in range(rounds):
            count = rows.count()
            if count >= max_rows or count == last_count:
                break
            last_count = count
            try:
                rows.nth(count - 1).scroll_into_view_if_needed()
            except Exception:
                pass
            self.page.mouse.wheel(0, 3000)
            time.sleep(2)

    def get_column_map(self, frame=None):
        """Đọc header bảng và trả về {'creator': idx, 'gmv': idx, 'orders': idx}"""
        frame = frame or self._active_frame()
        ths = frame.locator("th").all()
        header_texts = [th.inner_text().strip().lower() for th in ths]

        mapping = {}
        for key, words in COLUMN_KEYWORDS.items():
            for idx, text in enumerate(header_texts):
                if any(w in text for w in words):
                    mapping[key] = idx
                    break

        print(f"   [HEADER] {header_texts}")
        print(f"   [MAP] {mapping}")
        missing = [k for k in COLUMN_KEYWORDS if k not in mapping]
        if missing:
            print(f"   ⚠ Không nhận diện được cột: {missing}")
        return mapping

    def _cell_texts(self, row):
        """Trả về danh sách text của các ô td trong 1 hàng"""
        return [c.inner_text().strip() for c in row.locator("td").all()]

    def read_creator_identity(self, cells, column_map):
        """Lấy name và username từ list cells (đã đọc sẵn từ 1 lần _cell_texts)."""
        idx = column_map.get("creator")
        if idx is None or idx >= len(cells):
            return "", ""
        lines = [l.strip() for l in cells[idx].split("\n") if l.strip()]
        if not lines:
            return "", ""

        # Dòng đầu tiên luôn là username/handle (không có @)
        username = lines[0]

        # Tìm name: bỏ qua các dòng "Cấp X", dòng tiếp theo là tên hiển thị
        name = ""
        for i in range(1, len(lines)):
            if lines[i].startswith("Cấp"):
                continue
            name = lines[i]
            break

        return name, username

    def read_row_metrics(self, cells, column_map):
        """Đọc followers (từ ô creator), GMV, số món, video, lượt xem TB, tỷ lệ tương tác
        từ list cells (đã đọc sẵn 1 lần)."""
        def cell_text(key):
            idx = column_map.get(key)
            if idx is None or idx >= len(cells):
                return ""
            return cells[idx]

        creator_text = cell_text("creator")
        m = FOLLOWER_RE.search(creator_text)
        followers = m.group(1).replace(" ", "") if m else ""

        return {
            "followers": followers,
            "gmv": cell_text("gmv"),
            "orders": cell_text("orders"),
            "videos": cell_text("videos"),
            "avg_views": cell_text("avg_views"),
            "engagement_rate": cell_text("engagement_rate"),
        }

    def is_already_invited(self, row, cells):
        """Kiểm tra creator đã được mời trước đây hay chưa.
        Cột cuối cùng trong bảng là nút 'Mời'; nếu text là 'Đã mời' / 'Đã mời trước đây'
        hoặc nút bị disabled thì coi như đã mời."""
        # Cột cuối cùng thường là nút mời
        invite_text = cells[-1].strip() if cells else ""
        if invite_text:
            lower = invite_text.lower()
            if "đã mời" in lower or "invited" in lower:
                return True
        # Kiểm tra thêm: nếu nút "Mời" trong row bị disabled
        try:
            btn = row.locator('button:has-text("Mời")')
            if btn.count() > 0 and not btn.first.is_enabled():
                return True
        except Exception:
            pass
        return False
    
    # tối đa 200 creator (`max_rows=200` ) và scroll tối đa 10 lần (`scroll_rounds=10`) cho mỗi keyword tìm kiếm
    def collect_creators_for_keyword(self, keyword, max_rows=100, scroll_rounds=5):
        """Tìm theo keyword, scroll tải thêm, trả về list dict creator đọc được."""
        print(f"\n🔍 Đang tìm kiếm với từ khóa: [{keyword}]")

        frame, rows = self.search_keyword(keyword)
        if rows is None:
            print(f"   -> Không có hàng kết quả cho từ khóa '{keyword}'.")
            return []

        self._scroll_to_load(frame, rows, max_rows, scroll_rounds)
        column_map = self.get_column_map(frame)

        results = []
        count = min(rows.count(), max_rows)
        for i in range(count):
            try:
                row = rows.nth(i)
                cells = self._cell_texts(row)
                # Debug: in raw text 3 creator đầu tiên để kiểm tra định dạng ô
                if i < 3:
                    print(f"   [DEBUG row {i}] raw cells: {cells}")
                name, username = self.read_creator_identity(cells, column_map)
                if i < 3:
                    print(f"   [DEBUG row {i}] name='{name}' username='{username}'")
                if not username:
                    if i < 3:
                        print(f"   [DEBUG row {i}] -> skip (username rỗng)")
                    continue
                metrics = self.read_row_metrics(cells, column_map)
                results.append({"name": name, "username": username, **metrics})
                if i < 3:
                    print(f"   [DEBUG row {i}] -> OK, metrics={metrics}")
            except Exception as e:
                import traceback
                print(f"   ⚠ Lỗi đọc dòng {i}: {e}")
                traceback.print_exc()

        print(f"   -> Thu thập {len(results)} creator cho '{keyword}'.")
        return results



    # Kiểm tra shop đang đăng nhập
    def check_current_shop(self, frame=None):
        """Kiểm tra shop hiện tại bằng cách đọc shop_id trực tiếp trên URL"""
        
        # Mapping giữa Shop ID và tên shop thực tế
        SHOP_ID_MAP = {
            "7496118075388561529": "LUNAVÉ VIETNAM",
            "7495511580297103644": "RIZIN SHOP",
        }

        frame = frame or self._active_frame()
        
        try:
            # Lấy URL hiện tại của trang
            current_url = frame.page.url if hasattr(frame, "page") else self.page.url
            
            # Phân tích cú pháp URL để lấy giá trị của tham số shop_id
            parsed_url = urlparse(current_url)
            query_params = parse_qs(parsed_url.query)
            
            shop_ids = query_params.get("shop_id", [])
            if not shop_ids:
                print("   ⚠ URL hiện tại không chứa tham số shop_id!")
                return None
                
            current_shop_id = shop_ids[0]
            shop_name = SHOP_ID_MAP.get(current_shop_id, f"Unknown Shop (ID: {current_shop_id})")
            
            print(f"   [URL] {current_url}")
            print(f"   [DETECTED SHOP ID] {current_shop_id} -> {shop_name}")
            return current_shop_id, shop_name

        except Exception as e:
            print(f"   [LỖI] Không thể đọc shop_id từ URL: {e}")
            return None, None

