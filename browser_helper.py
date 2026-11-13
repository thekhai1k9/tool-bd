import datetime
import os
import re
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from urllib.parse import urlparse, parse_qs
import time
import diagnostics
from config import SEARCH_PAGE_URL

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
        self.current_shop_id = None
        self.target_collaboration_url = None
        self.target_collaboration_shop_id = None

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
            diagnostics.capture_error(self.page, e)
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
                    if text.strip().lower() != txt:
                        continue

                    # Text có thể nằm trong span, checkbox nằm ở nhánh bên cạnh.
                    container = el.locator(
                        "xpath=ancestor-or-self::*[.//input[@type='checkbox'] "
                        "or .//*[@role='checkbox']][1]"
                    )
                    if container.count() == 0:
                        continue

                    cb = container.locator('input[type="checkbox"]')
                    if cb.count() == 0:
                        cb = container.get_by_role("checkbox")
                    if cb.count() != 1:
                        continue
                    if not cb.is_checked():
                        if cb.is_visible():
                            cb.set_checked(True, timeout=2000)
                        else:
                            # TikTok dùng input ẩn; click input để phát sự kiện cho UI.
                            cb.evaluate("e => { if (!e.disabled && !e.checked) e.click(); }")
                        self.page.wait_for_timeout(300)
                    if cb.is_checked():
                        return True
                except Exception as e:
                    print(f"   [DEBUG] Không tick được checkbox '{text}': {e}")
                    continue
            time.sleep(0.5)
        return False

    def apply_category_filter(self, category_name):
        """Lọc theo 1 hạng mục sản phẩm: mở dropdown, tìm text, tích checkbox cạnh nó.
        Trả về True nếu chọn được, False nếu bỏ qua."""
        try:
            self.close_dropdown()
            category_filters = self.page.get_by_text("Hạng mục sản phẩm", exact=True)
            # Chọn hạng mục tiếp theo trên tab hiện tại, giữ các lựa chọn trước.
            if not any(
                category_filters.nth(i).is_visible()
                for i in range(category_filters.count())
            ):
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
            diagnostics.capture_error(self.page, e)
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
            self.open_tab("Người theo dõi")
            self.click_visible("Tổng số người theo dõi")

            # Nhận diện popup qua slider thực tế, không phụ thuộc class CSS.
            slider = self.page.locator('[data-tid="m4b_slider"]:visible')
            slider.wait_for(state="visible", timeout=10000)
            popup = slider.locator(
                "xpath=ancestor::*[count(.//input)=2][1]"
            )
            popup.wait_for(state="visible", timeout=5000)

            inputs = popup.locator('input:visible')
            if inputs.count() != 2:
                raise RuntimeError(
                    f"Cần 2 ô min/max, tìm thấy {inputs.count()}"
                )

            min_input = inputs.nth(0)
            max_input = inputs.nth(1)

            # Nhập max trước để không bị ràng buộc bởi max cũ.
            max_input.fill(str(max_followers))
            max_input.press("Tab")

            min_input.fill(str(min_followers))
            min_input.press("Tab")

            def read_number(field):
                return re.sub(r"\D", "", field.input_value())

            # Chờ giao diện nhận giá trị và định dạng lại.
            deadline = time.time() + 5
            while time.time() < deadline:
                if (
                    read_number(min_input) == str(min_followers)
                    and read_number(max_input) == str(max_followers)
                ):
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError(
                    f"Giá trị sau nhập: "
                    f"{min_input.input_value()} - "
                    f"{max_input.input_value()}"
                )

            self.close_dropdown()
            print(
                f"   ✓ Đã nhập followers: "
                f"{min_followers} - {max_followers}"
            )
            return True

        except Exception as e:
            diagnostics.capture_error(self.page, e)
            print(f"   ❌ Lọc followers thất bại: {e}")
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
            self._check_captcha(frame)
            empty = frame.get_by_text(re.compile(
                r"không tìm thấy.*nhà sáng tạo|không có kết quả|no results|no creators found",
                re.IGNORECASE,
            ))
            if any(empty.nth(i).is_visible() for i in range(empty.count())):
                return None, None
            raise RuntimeError(
                f"Chưa tải được kết quả keyword '{keyword}'; giữ checkpoint, không coi là hết kết quả."
            )
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
    
    def _check_captcha(self, frame=None):
        for surface in (self.page, frame):
            if surface is None:
                continue
            challenge = surface.locator(
                'iframe[src*="captcha"]:visible, #captcha-verify-container:visible, '
                '[id*="captcha_container"]:visible'
            )
            if challenge.count():
                raise RuntimeError(
                    "CAPTCHA đang chặn thao tác. Đã giữ checkpoint; "
                    "xác minh thủ công trên phiên hiện tại rồi chạy tiếp."
                )

    def _pace_creator(self):
        # Áp dụng cả creator bị loại, không chỉ người được ghi Sheet.
        previous = getattr(self, "_last_creator_time", 0)
        delay = max(0, 5 - (time.monotonic() - previous))
        if delay:
            self.page.wait_for_timeout(delay * 1000)
        self._last_creator_time = time.monotonic()

    def _creator_signature(self, rows, column_map):
        usernames = []
        for index in range(rows.count()):
            _, username = self.read_creator_identity(self._cell_texts(rows.nth(index)), column_map)
            usernames.append(username.strip().lstrip("@").lower())
        return tuple(usernames)

    def _wait_creator_results_change(self, frame, rows, previous, column_map, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._check_captcha(frame)
            loading = frame.locator(
                '.core-spin-loading:visible, .arco-spin-loading:visible, [aria-busy="true"]:visible'
            )
            if not loading.count():
                current = self._creator_signature(rows, column_map)
                if current and current != previous:
                    return True
            self.page.wait_for_timeout(500)
        if frame.locator(
            '.core-spin-loading:visible, .arco-spin-loading:visible, [aria-busy="true"]:visible'
        ).count():
            raise RuntimeError("Kết quả vẫn đang tải; giữ checkpoint, chưa đánh dấu hết keyword.")
        return False

    def _advance_creator_results(self, frame, rows, column_map):
        previous = self._creator_signature(rows, column_map)
        for _ in range(3):
            self._check_captcha(frame)
            scrolled = False
            if rows.count():
                last = rows.nth(rows.count() - 1)
                # Mỗi lượt chỉ một bước < 1 viewport để không bỏ qua dòng virtualized.
                scrolled = last.evaluate("""element => {
                    for (let parent = element.parentElement; parent; parent = parent.parentElement) {
                        const style = getComputedStyle(parent);
                        if (/(auto|scroll)/.test(style.overflowY) && parent.scrollHeight > parent.clientHeight) {
                            parent.scrollBy(0, Math.max(parent.clientHeight * 0.7, 1));
                            return true;
                        }
                    }
                    const root = element.ownerDocument.scrollingElement;
                    if (root) {
                        root.scrollBy(0, Math.max(root.clientHeight * 0.7, 1));
                        return true;
                    }
                    return false;
                }""")
            if not scrolled:
                viewport = self.page.viewport_size or {"height": 600}
                self.page.mouse.wheel(0, max(1, int(viewport["height"] * 0.7)))
            if self._wait_creator_results_change(frame, rows, previous, column_map):
                return True

        next_buttons = frame.locator(
            'button[aria-label="Next Page"]:visible, button[aria-label="Next page"]:visible, '
            'button[aria-label="Trang tiếp"]:visible, '
            '.core-pagination-item-next:visible, .arco-pagination-item-next:visible'
        )
        for index in range(next_buttons.count()):
            button = next_buttons.nth(index)
            classes = button.get_attribute("class") or ""
            if not button.is_enabled() or button.get_attribute("aria-disabled") == "true" or "disabled" in classes:
                continue
            button.click()
            if self._wait_creator_results_change(frame, rows, previous, column_map, timeout=15):
                print("   -> Đã chuyển trang kết quả tiếp theo.")
                return True
            raise RuntimeError("Đã bấm trang tiếp nhưng chưa có kết quả mới; giữ checkpoint.")
        return False

    def iter_creators_for_keyword(self, keyword, seen_usernames=None):
        """Đọc từng lượt mới, scroll/phân trang; bên gọi dừng ngay khi đủ target."""
        print(f"\n🔍 Đang tìm kiếm với từ khóa: [{keyword}]")
        self._check_captcha()
        frame, rows = self.search_keyword(keyword)
        if rows is None:
            self._check_captcha(frame)
            print(f"   -> Không có hàng kết quả cho từ khóa '{keyword}'.")
            return
        column_map = self.get_column_map(frame)
        if "creator" not in column_map:
            raise RuntimeError("Không nhận diện được cột creator; không đánh dấu keyword đã duyệt.")
        seen = set(seen_usernames or ())
        windows_seen = set()
        window = 0
        while True:
            self._check_captcha(frame)
            signature = self._creator_signature(rows, column_map)
            if signature in windows_seen:
                print("   -> Kết quả lặp lại, chuyển keyword để tránh quét vô hạn.")
                return
            windows_seen.add(signature)
            window += 1
            for i in range(rows.count()):
                self._check_captcha(frame)
                row = rows.nth(i)
                cells = self._cell_texts(row)
                name, username = self.read_creator_identity(cells, column_map)
                normalized = username.strip().lstrip("@").lower()
                if not normalized or normalized in seen:
                    continue
                self._pace_creator()
                metrics = self.read_row_metrics(cells, column_map)
                invited = self.is_already_invited(row, cells)
                seen.add(normalized)
                yield {
                    "name": name, "username": username, **metrics,
                    "already_invited": invited, "keyword": keyword,
                    "window": window, "row": i + 1,
                }
            if not self._advance_creator_results(frame, rows, column_map):
                print("   -> Không có kết quả mới sau 3 lượt chờ/scroll; chuyển keyword.")
                return

    def collect_creators_for_keyword(self, keyword, max_rows=100, scroll_rounds=5):
        """Tương thích caller cũ; luồng DAILY dùng iterator không giới hạn 100 dòng."""
        from itertools import islice
        return list(islice(self.iter_creators_for_keyword(keyword), max_rows))



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
            self.current_shop_id = current_shop_id
            shop_name = SHOP_ID_MAP.get(current_shop_id, f"Unknown Shop (ID: {current_shop_id})")
            
            print(f"   [URL] {current_url}")
            print(f"   [DETECTED SHOP ID] {current_shop_id} -> {shop_name}")
            return current_shop_id, shop_name

        except Exception as e:
            print(f"   [LỖI] Không thể đọc shop_id từ URL: {e}")
            return None, None


    ############################################# CỘNG TÁC MỤC TIÊU TẠO LỜI MỜI ########################################################
    ####################################################################################################################################


    def go_to_target_collaboration(self):
        """Lưu URL danh sách lần đầu; quay thẳng về đó sau trang gửi thành công."""
        print("\n👉 Đang chuyển sang trang 'Cộng tác mục tiêu'...")
        diagnostics.set_context(stage="target_navigation", creator=None, keyword=None)
        try:
            page = self.page
            source_shop_id = parse_qs(urlparse(page.url).query).get("shop_id", [None])[0]
            expected_shop_id = self.current_shop_id or source_shop_id
            if self.target_collaboration_url and self.target_collaboration_shop_id != expected_shop_id:
                self.target_collaboration_url = None
            if self.target_collaboration_url:
                page.goto(self.target_collaboration_url, wait_until="domcontentloaded", timeout=30000)
            else:
                target_menu = page.get_by_text("Cộng tác mục tiêu", exact=True)
                if not any(target_menu.nth(i).is_visible() for i in range(target_menu.count())):
                    self.click_visible("Cộng tác", timeout=10000)
                self.click_visible("Cộng tác mục tiêu", timeout=10000)

            page.get_by_role("button", name="Mời cộng tác", exact=True).first.wait_for(
                state="visible", timeout=15000,
            )
            destination = urlparse(page.url)
            destination_shop_id = parse_qs(destination.query).get("shop_id", [None])[0]
            if expected_shop_id and destination_shop_id and destination_shop_id != expected_shop_id:
                raise RuntimeError("Trang Cộng tác mục tiêu chuyển sang shop khác; không tạo lời mời.")
            if destination.path.rstrip("/").endswith("/create"):
                raise RuntimeError("Vẫn ở trang tạo/gửi lời mời cũ, chưa về danh sách Cộng tác mục tiêu.")
            self.target_collaboration_url = page.url
            self.target_collaboration_shop_id = expected_shop_id or destination_shop_id
            print("   ✓ Đã vào trang Cộng tác mục tiêu.")
            return True
        except Exception as e:
            diagnostics.capture_error(self.page, e)
            self.target_collaboration_url = None
            print(f"   ❌ Lỗi khi điều hướng vào Cộng tác mục tiêu: {e}")
            return False

    def _set_creator_page_size(self, required=True):
        """Chọn 50/Trang trong riêng phần Chọn nhà sáng tạo."""
        search = self.page.get_by_placeholder("Tìm kiếm nhà sáng tạo theo tên người dùng hoặc ID người dùng")
        region = search.locator(
            "xpath=ancestor::*[contains(concat(' ',normalize-space(@class),' '),' select-creators ')][1]"
        )
        if region.count() == 0:
            region = search.locator("xpath=ancestor::*[.//table/thead//th[contains(.,'Nhà sáng tạo')]][1]")
        if region.count() == 0:
            if not required:
                return False  # Bảng rỗng có thể chưa render footer; thử sau creator đầu tiên.
            raise RuntimeError("Chưa thấy Kích cỡ trang của bảng creator; chưa gửi.")
        combo = region.locator('.core-pagination-option[aria-label="Kích cỡ trang"] [role="combobox"]:visible')
        if combo.count() == 0 and not required:
            return False
        if combo.count() != 1:
            raise RuntimeError("Không xác định được duy nhất Kích cỡ trang của bảng creator.")
        value = combo.locator(".core-select-view-value")
        is_fifty = lambda: bool(re.fullmatch(r"\s*50\s*/\s*Trang\s*", value.inner_text(), re.IGNORECASE))
        if is_fifty():
            return True
        combo.click(timeout=5000)
        popup_id = combo.get_attribute("aria-controls")
        if not popup_id or not re.fullmatch(r"[\w-]+", popup_id):
            raise RuntimeError("Dropdown Kích cỡ trang không có aria-controls hợp lệ.")
        popup = self.page.locator(f'[id="{popup_id}"]:visible')
        popup.wait_for(state="visible", timeout=5000)
        selected_option = None
        # DOM thực tế dùng '50/trang'; giữ các nhãn khác để tương thích.
        for label in ("50/Trang", "50/trang", "50"):
            option = popup.get_by_role("option", name=label, exact=True)
            if option.count() == 0:
                option = popup.get_by_text(label, exact=True)
            try:
                option.wait_for(state="visible", timeout=2000)
            except PWTimeout:
                continue
            if option.count() != 1:
                raise RuntimeError(f"Tùy chọn {label!r} không duy nhất trong popup Kích cỡ trang.")
            selected_option = option
            break
        if selected_option is None:
            popup_text = popup.inner_text()
            print(f"   [DEBUG] DOM popup #{popup_id}: {popup.inner_html()[:2500]}")
            raise RuntimeError(f"Không thấy mục 50, 50/trang hoặc 50/Trang trong popup #{popup_id}; nội dung: {popup_text[:800]!r}")
        selected_option.click(timeout=5000)
        deadline = time.monotonic() + 5
        while not is_fifty():
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Chưa đổi được 50/Trang; hiện tại: {value.inner_text()!r}")
            self.page.wait_for_timeout(100)
        print("   ✓ Bảng Nhà sáng tạo đã đặt 50/Trang.")
        return True

    def _check_invitation_creator_page(self, table, expected, select):
        """Tick tổng một trang; đọc username từ cả dòng, không phụ thuộc text element."""
        names, checkboxes = [], []
        for row in table.locator("tbody tr:visible").all():
            checkbox = row.locator('input[type="checkbox"]')
            if checkbox.count() == 0:
                continue
            text = row.inner_text()
            matches = [
                name for name in expected
                if re.search(rf"(?<![\w.])@?{re.escape(name)}(?![\w.])", text, re.IGNORECASE)
            ]
            if len(matches) != 1 or checkbox.count() != 1 or checkbox.is_disabled():
                raise RuntimeError(f"Dòng creator không khớp duy nhất danh sách đợt hoặc checkbox bị khóa: {text!r}")
            if matches[0] in names:
                raise RuntimeError(f"Creator {matches[0]} xuất hiện lặp trong bảng; chưa gửi.")
            names.append(matches[0])
            checkboxes.append(checkbox)
        if not names:
            raise RuntimeError("Trang bảng creator chưa có dòng có thể chọn; chưa gửi.")

        if select and not all(checkbox.is_checked() for checkbox in checkboxes):
            master = table.locator('thead th.core-table-checkbox input[type="checkbox"]')
            if master.count() != 1 or master.is_disabled():
                raise RuntimeError("Không xác định được checkbox tổng của bảng Nhà sáng tạo.")
            if not master.is_checked():
                master.locator("xpath=ancestor::label[1]").locator(".core-checkbox-mask").click(timeout=5000)

        deadline = time.monotonic() + (5 if select else 0)
        while not all(checkbox.is_checked() for checkbox in checkboxes):
            if time.monotonic() >= deadline:
                raise RuntimeError("Có creator chưa được tick sau chọn tổng trên trang 50/Trang; chưa gửi.")
            self.page.wait_for_timeout(100)
        return tuple(names)

    def _creator_selection_page_button(self, region, direction):
        controls = region.locator(
            f'.core-pagination-item-{direction}:visible, '
            f'.arco-pagination-item-{direction}:visible'
        )
        if controls.count() > 1:
            raise RuntimeError("Vùng bảng creator có nhiều bộ phân trang; không tự chọn nhầm bảng.")
        if controls.count() == 0:
            return None
        control = controls.first
        if (
            not control.is_enabled()
            or control.get_attribute("aria-disabled") == "true"
            or "disabled" in (control.get_attribute("class") or "")
        ):
            return None
        return control

    def _select_all_invitation_creators(self, creator_usernames):
        normalized = [str(name).strip().lstrip("@").lower() for name in creator_usernames]
        expected = set(normalized)
        if not expected or "" in expected or len(expected) != len(normalized):
            raise RuntimeError("Danh sách đợt trống hoặc có username trùng; chưa gửi.")
        if len(expected) > 50:
            raise RuntimeError("Một đợt chỉ được tối đa 50 creator; chưa gửi.")
        self._set_creator_page_size(required=True)
        headers = self.page.locator("thead").filter(has_text=re.compile("Nhà sáng tạo", re.IGNORECASE))
        tables = self.page.locator("table:visible").filter(has=headers)
        tables.first.wait_for(state="visible", timeout=10000)
        if tables.count() != 1:
            raise RuntimeError("Không xác định được duy nhất bảng Nhà sáng tạo; chưa gửi.")
        table = tables.first
        containers = table.locator(
            "xpath=ancestor::*[.//*[contains(@class,'core-pagination') "
            "or contains(@class,'arco-pagination')]][1]"
        )
        region = containers if containers.count() == 1 else table
        if region.locator("table:visible").count() > 1:
            raise RuntimeError("Không giới hạn được phân trang vào riêng bảng Nhà sáng tạo; chưa gửi.")
        total = re.search(r"Tổng số hàng\s*:\s*(\d+)", region.inner_text(), re.IGNORECASE)
        if total and int(total.group(1)) != len(expected):
            raise RuntimeError(f"Bảng có {total.group(1)} creator, đợt yêu cầu {len(expected)}; chưa gửi.")

        # Không chuyển trang sau khi chọn: TikTok có thể làm mất lựa chọn trang trước.
        deadline = time.monotonic() + 10
        while table.locator("tbody tr:visible").count() != len(expected):
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Chưa hiển thị đủ {len(expected)} creator trên cùng một trang 50/Trang; chưa gửi.")
            self.page.wait_for_timeout(200)
        if any(self._creator_selection_page_button(region, direction) is not None for direction in ("prev", "next")):
            raise RuntimeError("Danh sách creator vẫn còn nhiều trang sau khi đặt 50/Trang; chưa gửi.")
        names = self._check_invitation_creator_page(table, expected, select=True)
        if set(names) != expected:
            raise RuntimeError(f"Danh sách creator trên trang không khớp đợt; thiếu {sorted(expected - set(names))}; chưa gửi.")
        return len(expected)

    def _record_invitation_state(self, callback, status, stage, **details):
        diagnostics.set_context(stage=stage)
        diagnostics.event(f"Invitation state: status={status}, stage={stage}")
        self.last_invitation_state = {
            **getattr(self, "last_invitation_state", {}),
            "status": status, "stage": stage, "error": None, **details,
        }
        if callback is not None:
            callback(dict(self.last_invitation_state))

    def _send_target_invitation(self, invitation_name, added_count, batch_index, on_state_change):
        confirm = input(f"👉 Bạn có muốn GỬI lời mời Đợt {batch_index} này không? (y/n): ")
        if confirm.strip().lower() != "y":
            self._record_invitation_state(on_state_change, "ready", "awaiting_approval", error="Người dùng chưa duyệt gửi.")
            print(f"⏸ Chưa gửi Đợt {batch_index}; danh sách được giữ để chạy tiếp.")
            return False, invitation_name, 0
        success_message = self.page.get_by_text("Đã gửi lời mời cộng tác!", exact=True)
        success_message.wait_for(state="hidden", timeout=3000)
        send_button = self.page.locator("button:has-text('Gửi')")
        send_button.wait_for(state="visible", timeout=5000)
        self._record_invitation_state(on_state_change, "sending", "send", invitation_name=invitation_name)
        send_button.click(force=True)
        print("Đã bấm Gửi, đang chờ TikTok xác nhận...")
        try:
            success_message.wait_for(state="visible", timeout=30000)
        except PWTimeout:
            self._record_invitation_state(
                on_state_change, "sending", "verify_send", error="Không thấy thông báo gửi thành công trong 30 giây."
            )
            diagnostics.capture_error(self.page)
            print("CHƯA XÁC NHẬN sau thao tác Gửi. Giữ trạng thái sending; không tự gửi lại.")
            return False, invitation_name, 0
        self._record_invitation_state(on_state_change, "sent", "log_history", total_sent=added_count)
        print(f"✓ TikTok xác nhận đã gửi lời mời: {invitation_name}")
        return True, invitation_name, added_count

    def _configure_invitation_details(self, sku_info, invite_content, batch_index, attempt, on_state_change):
        page = self.page
        # 1. Bấm nút 'Mời cộng tác' góc trên phải
        print("👉 Bấm 'Mời cộng tác'...")
        page.locator("button:has-text('Mời cộng tác')").first.click(force=True)
        time.sleep(2)

        ##########################################################################
        # 2. Tạo tên lời mời chuẩn dạng: BD_AUTO_[4 số đuôi ID SKU]-[NGÀY/THÁNG]_[ĐỢT] (VD: BD_AUTO_3257-07/11_1)[cite: 2, 3]
        ##########################################################################
        sku_id = str(sku_info.get("sku_id", ""))
        suffix_4_digits = sku_id[-4:] if len(sku_id) >= 4 else sku_id
        today_str = datetime.datetime.now().strftime("%d/%m")
        invitation_name = f"BD_AUTO_{suffix_4_digits}-{today_str}_{batch_index}"
        if attempt > 1:
            invitation_name += f"_R{attempt}"
        self._record_invitation_state(on_state_change, "draft", "configure_invitation", invitation_name=invitation_name)

        print(f"   [+] Tên lời mời: {invitation_name}")

        # Điền tên lời mời
        page.get_by_placeholder("Tên lời mời").fill(invitation_name, force=True)
        time.sleep(0.5)

        ######################################################################
        # 3. Chọn ngày kết thúc hiệu lực = hôm nay + 30 ngày
        ######################################################################
        print("   [+] Thiết lập thời hạn hiệu lực...")
        target = datetime.datetime.now() + datetime.timedelta(days=30)

        date_input = page.locator("input.core-picker-start-time[placeholder='Ngày kết thúc']")
        date_input.click(force=True)

        # Nhãn "01 / 2026" và popup lịch
        header_value = page.locator("div.core-picker-header-value").first
        header_value.wait_for(state="visible", timeout=5000)
        panel = page.locator("div.core-panel-date:visible").first

        # Nút ‹ nằm ngay trước nhãn, › nằm ngay sau nhãn
        prev_btn = header_value.locator("xpath=preceding-sibling::div[contains(@class,'core-picker-header-icon')][1]")
        next_btn = header_value.locator("xpath=following-sibling::div[contains(@class,'core-picker-header-icon')][1]")

        # Bấm cho đến khi popup hiển thị đúng tháng và năm
        for _ in range(24):
            m, y = map(int, re.findall(r"\d+", header_value.inner_text()))
            if (y, m) == (target.year, target.month):
                break
            if (y, m) < (target.year, target.month):
                next_btn.click()
            else:
                prev_btn.click()
            time.sleep(0.3)

        # Chọn ô ngày trong phần thân lịch (không lấy ô của tháng khác nếu có thể)
        body = panel.locator("div.core-picker-body")
        body.get_by_text(str(target.day), exact=True).first.click()
        time.sleep(0.5)

        # Xác nhận đã điền
        value = date_input.input_value()
        if value:
            print(f"     [✓] Hiệu lực đến: {value}")
        else:
            print("     ⚠️ Ô ngày vẫn trống, kiểm tra lại selector ô ngày.")

        # (Lưu ý: Số Zalo trên app đã tự động có sẵn)

        # 4. Điền nội dung lời mời
        if invite_content:
            msg_input = page.get_by_placeholder("Nhập nội dung lời mời")
            if msg_input.is_visible():
                msg_input.fill(invite_content, force=True)

        # 5 . Loại nội dung ưu tiên: Không có ưu tiên (Mặc định)[cite: 2]
        return invitation_name, sku_id

    def _configure_invitation_product(self, sku_id, sku_info, on_state_change):
        page = self.page
        # 6. Chọn sản phẩm (SKU)
        print("   [+] Chuyển chế độ tìm kiếm sang 'ID sản phẩm'...")
        self._record_invitation_state(on_state_change, "draft", "select_product")

        # ----- Bước 6.1: Bấm vào thanh tiêu đề "Chọn sản phẩm" để xổ mục xuống (nếu đang đóng)
        section_header = page.locator("text=Chọn sản phẩm").first
        section_header.scroll_into_view_if_needed()
        section_header.click(force=True)
        time.sleep(1)

        # ---- Bước 6.2: Bấm nút 'Thêm sản phẩm' màu xanh để trượt panel bên phải ra
        print("   [+] Bấm 'Thêm sản phẩm' để mở bảng chọn...")
        add_product_btn = page.locator("button:has-text('Thêm sản phẩm')").first
        add_product_btn.scroll_into_view_if_needed()
        add_product_btn.click(force=True)
        time.sleep(1.5) # Chờ panel bên phải trượt ra hoàn toàn

        # --- BƯỚC 6.3: Tương tác với Panel "Thêm từ cửa hàng" bên phải ---
        print(f"   [+] Đang tìm và nhập SKU ID: {sku_id}")

        # ---- BƯỚC 6.4.1: Ô tìm kiếm sản phẩm trong panel --> Đổi loại tìm kiếm thành "ID sản phẩm" ---
        dropdown_trigger = page.locator("span.core-trigger, [class*='core-trigger'], .core-select").filter(has_text="Tên sản phẩm").first
        if dropdown_trigger.count() == 0:
            dropdown_trigger = page.locator("text=Tên sản phẩm").first

        dropdown_trigger.click(force=True)
        time.sleep(0.8)

        # ---- BƯỚC 6.4.2: Chọn "ID sản phẩm" trong menu dropdown
        option_id = page.locator(".core-select-option").filter(has_text="ID sản phẩm").first
        option_id.click(force=True)
        time.sleep(0.5)
        print(f"   ✓ Đã chuyển sang chế độ ID sản phẩm thành công.")

        # --- BƯỚC 6.4.3: Nhập SKU ID vào ô tìm kiếm ---
        print(f"   [+] Nhập SKU ID vào ô tìm kiếm: {sku_id}")
        search_input = page.locator(".core-drawer-body input[data-tid='m4b_input_search'], input[data-tid='m4b_input_search']").first

        search_input.wait_for(state="visible", timeout=5000)
        time.sleep(0.5)

        search_input.scroll_into_view_if_needed()
        search_input.click(force=True)
        search_input.fill("")
        time.sleep(0.3)

        search_input.type(str(sku_id), delay=60)
        time.sleep(0.3)
        page.keyboard.press("Enter")

        print(f"   ✓ Đã điền xong SKU ID: {sku_id}, đang chờ kết quả lọc...")
        time.sleep(3.0) # Chờ hệ thống TikTok Shop load kết quả lọc theo ID

        # --- BƯỚC 6.4.4: Tick chọn checkbox sản phẩm kết quả ---
        print(f"   [+] Đang chọn checkbox cho SKU ID: {sku_id}")
        if not sku_id.isdigit():
            raise RuntimeError(f"SKU ID không hợp lệ: {sku_id!r}")
        sku_checkbox_selector = f'input[type="checkbox"][value="{sku_id}"]'
        sku_rows = page.locator("tr.core-table-tr:visible").filter(
            has=page.locator(sku_checkbox_selector)
        )
        row = sku_rows.first
        try:
            row.wait_for(state="visible", timeout=10000)
        except PWTimeout as exc:
            raise RuntimeError(
                f"Không thấy dòng sản phẩm có checkbox value={sku_id}. "
                "Chưa chọn sản phẩm, chưa gửi lời mời. "
                "Kiểm tra lại kết quả tìm sản phẩm."
            ) from exc
        if sku_rows.count() == 1:
            checkbox = row.locator(sku_checkbox_selector)
            if checkbox.count() != 1 or checkbox.is_disabled():
                raise RuntimeError(f"Checkbox SKU {sku_id} không duy nhất hoặc bị vô hiệu hóa")
            if not checkbox.is_checked():
                mask = checkbox.locator(
                    'xpath=ancestor::label[@data-tid="m4b_checkbox"][1]'
                ).locator(".core-checkbox-mask")
                mask.click(timeout=5000)
            from playwright.sync_api import expect
            expect(checkbox).to_be_checked(timeout=5000)
        else:
            raise RuntimeError(f"Không xác định được duy nhất sản phẩm SKU {sku_id}")

        print(f"   ✓ Đã tick chọn thành công SKU ID: {sku_id}")
        time.sleep(1)

        # ---- BƯỚC 6.4.5: Bấm nút Xác nhận / Thêm ở góc dưới panel bên phải để hoàn tất chọn sản phẩm
        print("   [+] Xác nhận thêm sản phẩm vào lời mời...")
        confirm_btn = page.locator(".core-drawer-footer button:has-text('Thêm'), button:has-text('Thêm')").last
        confirm_btn.scroll_into_view_if_needed()
        if confirm_btn.is_visible():
            confirm_btn.click(force=True)
            print("   ✓ Đã bấm nút 'Thêm' thành công.")
        else:
            # Fallback bấm nút có thể đang sáng ở footer
            page.locator(".core-drawer-footer button").last.click(force=True)

        time.sleep(1.5)

        #   BƯỚC 6.4.6: Bật switch "Hoa hồng Quảng cáo cửa hàng" và nhập tỉ lệ hoa hồng
        print("   [+] Đang cấu hình tỉ lệ hoa hồng...")
        def _fmt_rate(v):
            # "15%" -> "15", 0.15 -> "15"
            s = str(v).strip().replace('%', '').replace(',', '.')
            try:
                n = float(s)
            except ValueError:
                return ''
            if n <= 1:
                n *= 100
            return f"{n:g}"
        std_rate = _fmt_rate(sku_info.get('base_commission', ''))
        ads_rate = _fmt_rate(sku_info.get('ads_commission', ''))

        prod_row = page.locator(".core-table-container tbody tr").first
        prod_row.wait_for(state="visible", timeout=5000)

        ads_switch = prod_row.locator(".core-switch").first
        ads_switch.scroll_into_view_if_needed()
        if ads_switch.get_attribute("aria-checked") != "true":
            ads_switch.click(force=True)
            time.sleep(0.8)

        rate_inputs = prod_row.locator("input[placeholder*='1,00-80,00']")

        std_input = rate_inputs.nth(0)
        std_input.click(force=True)
        std_input.fill(std_rate)
        time.sleep(0.3)

        ads_input = rate_inputs.nth(1)
        ads_input.click(force=True)
        ads_input.fill(ads_rate)
        time.sleep(0.5)

        print(f"   ✓ Tỉ lệ tiêu chuẩn: {std_input.input_value()}% | Tỉ lệ quảng cáo: {ads_input.input_value()}%")


        #####################################################################################
        # 6. Cài đặt Hàng mẫu (Bật cung cấp hàng mẫu & chọn cài đặt cấp sản phẩm)[cite: 2, 6]
        #####################################################################################

    def _configure_invitation_samples(self):
        page = self.page
        print("   [+] Cấu hình hàng mẫu miễn phí cấp sản phẩm...")
        sample_header = page.locator("text=Cài đặt hàng mẫu miễn phí").first
        if sample_header.count() > 0:
            sample_header.evaluate("el => el.click()")
            time.sleep(0.8) # Chờ hiệu ứng trượt mở của giao diện TikTok Shop

        # 2. Click chọn "Sử dụng cài đặt hàng mẫu cấp sản phẩm" bên trong
        sample_option = page.locator("text=Sử dụng cài đặt hàng mẫu cấp sản phẩm").first
        if sample_option.count() > 0:
            sample_option.evaluate("el => el.click()")
            print("   ✓ Đã chọn 'Sử dụng cài đặt hàng mẫu cấp sản phẩm' thành công.")
        else:
            print("   ✓ Khối cài đặt đã mở sẵn, tiếp tục...")

        # --- THÊM CREATOR VÀO LỜI MỜI (CHO ĐỢT NÀY) ---

    def _add_invitation_creators(self, creator_usernames, batch_index, on_state_change):
        page = self.page
        print(f"\n👉 Đang thêm {len(creator_usernames)} nhà sáng tạo vào Đợt {batch_index}...")
        self._record_invitation_state(on_state_change, "draft", "add_creators")
        creator_header = page.locator("text=Chọn nhà sáng tạo").first
        if creator_header.count() > 0:
            creator_header.evaluate("el => el.click()")
            time.sleep(1.0)


                    # ==========================================
        # GIAI ĐOẠN 1: Gõ tìm và đưa từng creator xuống bảng
        # ==========================================
        self._record_invitation_state(on_state_change, "draft", "set_creator_page_size")
        page_size_ready = self._set_creator_page_size(required=False)
        self._record_invitation_state(on_state_change, "draft", "add_creators")
        failed_creators = []
        for username in creator_usernames:
            username = str(username).strip()
            diagnostics.set_context(creator=username)
            search_creator = page.get_by_placeholder("Tìm kiếm nhà sáng tạo theo tên người dùng hoặc ID người dùng")
            search_creator.wait_for(state="visible", timeout=5000)

            # Khớp chính xác theo từ, không phân biệt hoa thường
            exact = re.compile(rf"(?<![\w.]){re.escape(username)}(?![\w.])", re.IGNORECASE)
            added_ok = False

            for attempt in range(1, 4):
                # 1. Đóng popup cũ, focus và xóa sạch ô input
                page.keyboard.press("Escape")
                search_creator.click()
                search_creator.fill("")
                time.sleep(0.3)

                # 2. Gõ từng ký tự để kích hoạt API
                search_creator.press_sequentially(username, delay=120)
                print(f"     [+] Lần {attempt}: đang tìm '{username}'")

                # 3. Chờ popup có mục khớp đúng username (thay cho sleep cố định)
                items = page.locator("div[role='listitem'].arco-list-item, .m4b-list-item")
                target = None
                deadline = time.time() + 6
                while time.time() < deadline and target is None:
                    for i in range(items.count()):
                        it = items.nth(i)
                        try:
                            if exact.search(it.inner_text(timeout=500)):
                                target = it
                                break
                        except Exception:
                            continue
                    if target is None:
                        time.sleep(0.3)

                if target is None:
                    print(f"     ⚠️ Không thấy '{username}' trong popup, thử lại...")
                    continue

                # 4. Click thật, không dùng JS click
                target.click()

                # 5. Xác minh username đã xuất hiện trong bảng
                try:
                    page.locator(".core-table-container").get_by_text(exact).first.wait_for(
                        state="visible", timeout=5000
                    )
                    print(f"     [✓] Đã đưa creator '{username}' xuống bảng.")
                    if not page_size_ready:
                        self._record_invitation_state(on_state_change, "draft", "set_creator_page_size")
                        page_size_ready = self._set_creator_page_size(required=True)
                        self._record_invitation_state(on_state_change, "draft", "add_creators")
                    added_ok = True
                    break
                except PWTimeout:
                    print(f"     ⚠️ Chưa thấy '{username}' trong bảng, thử lại...")

            if not added_ok:
                print(f"     ❌ Không thêm được creator '{username}' sau 3 lần.")
                failed_creators.append(username)

            # Dọn popup trước khi sang creator tiếp theo
            page.keyboard.press("Escape")
            time.sleep(0.5)

        # ==========================================
        # GIAI ĐOẠN 2: Tối đa 50 người trên một trang, tick tổng một lần.
        # ==========================================
        return failed_creators

    def _select_invitation_creators(self, creator_usernames, batch_index, failed_creators, on_state_change):
        page = self.page
        print("\n   [+] Đang tick checkbox tổng trên một trang 50/Trang...")
        diagnostics.set_context(creator=None)
        self._record_invitation_state(on_state_change, "draft", "select_creators")
        time.sleep(1.5)
        if failed_creators:
            raise RuntimeError(f"Có creator chưa thêm được vào bảng: {failed_creators}; chưa gửi.")
        added_count = self._select_all_invitation_creators(creator_usernames)
        time.sleep(1.5)
        print(f"\n✅ Đã hoàn tất cấu hình lời mời Đợt {batch_index} cho {added_count} creator.")
        if failed_creators:
            print(f"     ⚠️ Các creator không thêm được: {failed_creators}")
        return added_count

    def create_target_invitation(self, sku_info, invite_content, creator_usernames, batch_index=1,
                                 on_state_change=None, attempt=1):
        """
        Thực hiện toàn bộ tạo lời mời cộng tác mục tiêu + thêm creator vào lời mời (Theo đợt tối đa 50 người)[cite: 2, 3]
        """
        page = self.page
        self.last_invitation_state = {}
        diagnostics.set_context(batch=batch_index, sku=sku_info.get("sku_id"), creator=None, keyword=None)
        try:
            self._record_invitation_state(on_state_change, "draft", "configure_invitation")
            invitation_name, sku_id = self._configure_invitation_details(
                sku_info, invite_content, batch_index, attempt, on_state_change,
            )
            self._configure_invitation_product(sku_id, sku_info, on_state_change)
            self._configure_invitation_samples()
            failed_creators = self._add_invitation_creators(creator_usernames, batch_index, on_state_change)
            added_count = self._select_invitation_creators(
                creator_usernames, batch_index, failed_creators, on_state_change,
            )

            # --- XÁC NHẬN TRƯỚC KHI GỬI ---
            print("\n=======================================================")
            print(f" ⚠️  KIỂM TRA LẠI THÔNG TIN BẢN NHÁP LỜI MỜI (ĐỢT {batch_index}):")
            print(f" - Tên lời mời: {invitation_name}")
            print(f" - SKU ID: {sku_id} ({sku_info.get('product')})")
            print(f" - Số lượng creator thực tế thêm: {added_count}")
            print(f" - Số lượng yêu cầu trong đợt: {len(creator_usernames)}")
            print("=======================================================")

            if failed_creators or added_count != len(creator_usernames) or added_count == 0:
                raise RuntimeError(
                    f"Đã chọn {added_count}/{len(creator_usernames)} creator; "
                    f"thêm thất bại: {failed_creators}; chưa gửi."
                )
            
            self._record_invitation_state(on_state_change, "ready", "awaiting_approval")
            return self._send_target_invitation(invitation_name, added_count, batch_index, on_state_change)

        except Exception as e:
            diagnostics.capture_error(page, e)
            state = self.last_invitation_state
            self._record_invitation_state(
                on_state_change, state.get("status", "draft"), state.get("stage", "configure_invitation"), error=str(e),
            )
            print(f"❌ Đợt {batch_index} lỗi ở bước {state.get('stage', 'configure_invitation')}: {e}")
            return False, state.get("invitation_name"), 0

    def _chat_recipient_popup(self, chat_page):
        title = chat_page.get_by_text("Gửi lời mời", exact=True).filter(visible=True)
        title.wait_for(state="visible", timeout=10000)
        popup = title.locator(
            "xpath=ancestor::*[.//button[normalize-space(.)='Chia sẻ'] and .//tbody][1]"
        )
        if popup.count() != 1:
            raise RuntimeError("Không xác định được duy nhất popup chia sẻ; chưa gửi chat.")
        return popup

    def _scan_chat_recipients(self, chat_page, creator_usernames):
        """Read only: scroll the recipient table, never click or change checkboxes."""
        expected = [str(name).strip().lstrip("@").lower() for name in creator_usernames]
        if not expected or len(set(expected)) != len(expected) or any(not name for name in expected):
            raise RuntimeError("Danh sách creator đợt chat trống hoặc trùng; chưa gửi.")
        popup = self._chat_recipient_popup(chat_page)
        content = popup.locator(".core-table-content-scroll")
        content.wait_for(state="visible", timeout=10000)
        if content.count() != 1:
            raise RuntimeError("Không xác định được duy nhất vùng danh sách creator trong popup.")
        content.locator("tbody tr.core-table-tr").first.wait_for(state="visible", timeout=10000)
        scroll_script = """(root, action) => {
            const viewport = [root, ...root.querySelectorAll('*')].find(el =>
                el.querySelector('tbody') && /(auto|scroll)/.test(getComputedStyle(el).overflowY)
                && el.scrollHeight > el.clientHeight + 1);
            if (!viewport) return {top: 0, bottom: true};
            if (action === 'reset') viewport.scrollTop = 0;
            if (action === 'next') viewport.scrollTop += Math.max(1, viewport.clientHeight * 0.7);
            return {top: viewport.scrollTop,
                bottom: viewport.scrollTop + viewport.clientHeight >= viewport.scrollHeight - 2};
        }"""
        content.evaluate(scroll_script, "reset")
        chat_page.wait_for_timeout(200)
        observed, settled = {}, 0
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            snapshot = content.locator("tbody tr.core-table-tr").evaluate_all("""rows => rows.map(row => {
                const names = row.querySelectorAll('span.text-neutral-text1.text-body-m-medium');
                const boxes = row.querySelectorAll('input[type="checkbox"]');
                const box = boxes[0];
                return {name: names.length === 1 ? names[0].textContent.trim() : null,
                    valid: names.length === 1 && boxes.length === 1,
                    checked: box ? box.checked : false,
                    disabled: box ? (box.disabled || box.closest('label')?.getAttribute('aria-disabled') === 'true') : false};
            })""")
            before = len(observed)
            for item in snapshot:
                if not item["valid"] or not re.fullmatch(r"@[\w.]+", item["name"] or ""):
                    raise RuntimeError("Không đọc được username/checkbox duy nhất trong dòng chat; chưa gửi.")
                name = item["name"].lstrip("@").lower()
                if name not in expected:
                    raise RuntimeError(f"Popup chứa creator ngoài đợt: {name}; chưa gửi chat.")
                state = (item["checked"], item["disabled"])
                if name in observed and observed[name] != state:
                    raise RuntimeError(f"Lựa chọn chat của {name} thay đổi trong lúc đọc; kiểm tra lại.")
                observed[name] = state
            position = content.evaluate(scroll_script, "read")
            if position["bottom"] and len(observed) == before:
                settled += 1
            else:
                settled = 0
            if settled >= 3:
                break
            content.evaluate(scroll_script, "next")
            chat_page.wait_for_timeout(300)
        else:
            raise RuntimeError("Đọc danh sách chat quá thời gian; chưa gửi.")
        missing = set(expected) - set(observed)
        if missing:
            raise RuntimeError(f"Chưa đọc đủ creator popup ({len(observed)}/{len(expected)}); thiếu: {sorted(missing)}")
        unchecked_available = [name for name in expected if not observed[name][0] and not observed[name][1]]
        if unchecked_available:
            raise RuntimeError(f"Creator chưa tích nhưng checkbox còn khả dụng: {unchecked_available}; không tự click.")
        selected = [name for name in expected if observed[name][0]]
        rate_limit = [name for name in expected if not observed[name][0]]
        counter = popup.get_by_text(re.compile(r"Đã chọn\s*\d+\s*/\s*\d+"))
        if counter.count() != 1:
            raise RuntimeError("Không đọc được duy nhất bộ đếm creator chat; chưa gửi.")
        match = re.search(r"Đã chọn\s*(\d+)\s*/\s*(\d+)", counter.inner_text())
        if not match or int(match.group(1)) != len(selected):
            raise RuntimeError("Bộ đếm chat không khớp checkbox đã đọc; chưa gửi.")
        print(f"   [+] Chat: {len(selected)}/{len(expected)} đã chọn; rate limit: {len(rate_limit)}.")
        return {"selected_usernames": selected, "rate_limit_usernames": rate_limit}

    def _open_saved_chat(self, chat_url):
        destination = urlparse(chat_url)
        query = parse_qs(destination.query)
        shop_ids, plan_ids = query.get('shop_id', []), query.get('plan_id', [])
        if (destination.scheme != 'https' or destination.netloc != 'affiliate.tiktok.com'
                or destination.path.rstrip('/') != '/seller/im' or not self.current_shop_id
                or shop_ids != [str(self.current_shop_id)] or len(plan_ids) != 1 or not plan_ids[0].isdigit()):
            raise RuntimeError('URL chat không hợp lệ hoặc không khớp shop đang đăng nhập; chưa gửi.')
        matches = [page for page in self.page.context.pages if page.url == chat_url and not page.is_closed()]
        if len(matches) > 1:
            raise RuntimeError('Có nhiều tab cùng URL chat; giữ một tab đúng lời mời rồi chạy lại.')
        if matches:
            return matches[0]
        chat_page = self.page.context.new_page()
        chat_page.goto(chat_url, wait_until='domcontentloaded', timeout=30000)
        actual = urlparse(chat_page.url)
        actual_query = parse_qs(actual.query)
        if (actual.scheme != destination.scheme or actual.netloc != destination.netloc
                or actual.path.rstrip('/') != '/seller/im'
                or actual_query.get('shop_id') != shop_ids or actual_query.get('plan_id') != plan_ids):
            raise RuntimeError('Trang chat chuyển sang shop hoặc lời mời khác; chưa gửi.')
        return chat_page

    def share_invitation_via_chat(self, creator_usernames, on_result=None, chat_url=None):
        """Share only the existing selection; persist counts before/after manual confirmation."""
        page = self.page
        diagnostics.set_context(stage="chat", creator=None, keyword=None)

        # Resume an existing invitation's chat without creating or sending another invitation.
        if chat_url is not None:
            chat_page = self._open_saved_chat(chat_url)
        else:
            msg_btn = page.get_by_role("button", name=re.compile("Nhắn tin cho nhà sáng tạo")).first
            msg_btn.wait_for(state="visible", timeout=10000)
            with page.context.expect_page(timeout=10000) as new_page_info:
                msg_btn.click()
            chat_page = new_page_info.value
        chat_page.wait_for_load_state("domcontentloaded")
        print(f"   [+] Trang tin nhắn: {chat_page.url}")
        result = {"selected_usernames": [], "rate_limit_usernames": [],
                  "expected_count": len(creator_usernames), "confirmed": False,
                  "share_clicked": False, "followup_count": 0, "chat_url": chat_page.url}

        def save_result():
            if on_result is not None:
                on_result({**result, "selected_usernames": list(result["selected_usernames"]),
                           "rate_limit_usernames": list(result["rate_limit_usernames"])})

        save_result()
        popup_title = chat_page.get_by_text("Gửi lời mời", exact=True).first
        popup_title.wait_for(state="visible", timeout=30000)
        time.sleep(1)
        selection = self._scan_chat_recipients(chat_page, creator_usernames)
        result.update(selection)
        save_result()
        if not selection["selected_usernames"]:
            print("   -> Không có creator khả dụng; không bấm Chia sẻ. Ghi 0 follow-up và danh sách rate limit.")
            result["confirmed"] = True
            save_result()
            chat_page.close()
            return result

        # 4. Bấm "Chia sẻ"
        share_btn = self._chat_recipient_popup(chat_page).get_by_role("button", name=re.compile(r"^\s*Chia sẻ\s*$"))
        share_btn.wait_for(state="visible", timeout=10000)
        if input("Xác nhận GỬI qua chat cho các creator đang chọn? (y/n): ").strip().lower() != "y":
            print("Không gửi qua chat; giữ tab để kiểm tra.")
            return result
        # Read again after operator approval in case the popup selection changed.
        if self._scan_chat_recipients(chat_page, creator_usernames) != selection:
            raise RuntimeError("Lựa chọn chat đã đổi sau xác nhận; chưa bấm Chia sẻ.")
        result["share_clicked"] = True
        save_result()
        share_btn.click()

        # Popup đóng/networkidle không chứng minh hàng đợi gửi đã hoàn tất.
        print("   [+] Đã bấm Chia sẻ. Giữ tab chat mở, chưa xác nhận gửi đủ.")
        print("   Kiểm tra từng người nhận và các cảnh báo giới hạn/lỗi trên TikTok.")
        completed = input(
            f"Chỉ khi đã xác minh gửi đủ {len(selection['selected_usernames'])} người đang chọn, "
            "nhập 'DA GUI DU' để đóng tab "
            "và tiếp tục. Nếu thiếu/chưa rõ, nhấn Enter để giữ tab và dừng: "
        ).strip()
        if completed != "DA GUI DU":
            print("   ⚠ Chưa xác nhận gửi đủ. Giữ tab chat; không tự gửi lại.")
            return result
        result.update(confirmed=True, followup_count=len(creator_usernames) - len(selection["rate_limit_usernames"]))
        save_result()
        chat_page.close()
        print("   ✓ Người dùng đã xác minh gửi đủ; đã đóng tab chat.")
        return result
