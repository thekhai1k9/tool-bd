import re
import datetime
import gspread
import diagnostics
import creator_rules


class GoogleSheetManager:
    def __init__(self, credentials_file, spreadsheet_url):
        self.client = gspread.service_account(filename=credentials_file)
        self.spreadsheet = self.client.open_by_url(spreadsheet_url)
        self._worksheets = {}

    def _worksheet(self, title):
        # Cache tab handles only; every cell/row read still reaches Google Sheets.
        if title not in self._worksheets:
            self._worksheets[title] = self.spreadsheet.worksheet(title)
        return self._worksheets[title]

    def clear_worksheet_cache(self):
        """Refresh handles after tabs are renamed, deleted or recreated during a run."""
        self._worksheets.clear()

    # ------------------------------------------------------------------ #
    # Đọc cấu hình tiêu chí
    # ------------------------------------------------------------------ #
    def load_skus(self):
        """Đọc tab 'CMS SKU' -> list cấu hình tiêu chí cho từng SKU/sản phẩm."""
        sheet = self._worksheet("CMS SKU")
        rows = sheet.get_all_values()
        if len(rows) < 2:
            return []

        header = [h.strip().lower() for h in rows[0]]

        def find_col(keywords):
            for i, h in enumerate(header):
                if any(k in h for k in keywords):
                    return i
            return None

        c_product = find_col(["sản phẩm"])
        c_shop = find_col(["shop"])
        c_sku = find_col(["id sku", "sku"])
        c_followers = find_col(["followers"])
        c_gmv = find_col(["gmv", "doanh thu"])
        c_orders = find_col(["số món", "đơn"])
        c_category = find_col(["ngành hàng", "hạng mục"])
        c_target = find_col(["mục tiêu"])
        c_commission_base = find_col(["commission tiêu chuẩn"])
        c_commission_ads = find_col(["commission ads"])

        skus = []
        for row in rows[1:]:
            def get(idx):
                return row[idx].strip() if idx is not None and idx < len(row) else ""

            product = get(c_product)
            sku_id = get(c_sku)
            shop_name = get(c_shop)
            if not product and not sku_id:
                continue

            target = self.parse_min_rule(get(c_target))
            # SKU có mục tiêu 0 hoặc để trống -> bỏ qua
            if not target or target <= 0:
                continue

            skus.append({
                "shop": shop_name,
                "product": product,
                "sku_id": sku_id,
                "followers_rule": get(c_followers),
                "gmv_rule": get(c_gmv),
                "orders_rule": get(c_orders),
                "categories": [c.strip() for c in get(c_category).split("\n") if c.strip()],
                "base_commission": get(c_commission_base),
                "ads_commission": get(c_commission_ads),
                "target": target,
            })
        return skus

    def load_keywords(self, sheet_name="LIST KEYWORD", optional=False):
        """Đọc tab keyword -> dict {tên sản phẩm: [keyword, ...]}.
        Hàng 2 (index 1) là tên sản phẩm theo cột; các hàng dưới là keyword."""
        try:
            sheet = self._worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            if not optional:
                raise
            print(f"   -> Chưa có tab '{sheet_name}', chỉ dùng nguồn keyword hiện có.")
            return {}
        rows = sheet.get_all_values()
        if len(rows) < 3:
            return {}

        product_row = rows[1]
        result = {}
        for col_idx, product in enumerate(product_row):
            product = (product or "").strip()
            keywords = []
            for row in rows[2:]:
                if col_idx < len(row) and row[col_idx].strip():
                    kw = row[col_idx].strip()
                    if kw not in keywords:
                        keywords.append(kw)
            if keywords:
                result[product] = keywords
        return result

    def load_existing_creators(self):
        """Đọc LIST LƯU TẠM: quét TẤT CẢ các cột từ hàng 4 trở xuống để lấy tất cả username
        đã lưu (mỗi cột = 1 sản phẩm)."""
        sheet = self._worksheet("LIST LƯU TẠM")
        rows = sheet.get_all_values()
        existing = set()
        # Bỏ 3 hàng đầu (ID SKU, tên SP, header "TÊN / ID KOC")
        for row in rows[3:]:
            for cell in row:
                cell = cell.strip()
                print("=====", cell)
                if cell and not cell.startswith("Cấp") and not re.match(r"^\d", cell):
                    # Chỉ lấy những chuỗi trông như username (không phải số, không phải "Cấp X")
                    norm = self.normalize_username(cell)
                    if norm:
                        existing.add(norm)
        return existing

    def get_product_column_map(self):
        """Đọc hàng 2 của LIST LƯU TẠM -> {tên sản phẩm (lower): chỉ số cột (1-based)}.
        Mỗi cột = 1 sản phẩm."""
        sheet = self._worksheet("LIST LƯU TẠM")
        row2 = sheet.row_values(2)
        mapping = {}
        for col_idx, name in enumerate(row2):
            name = (name or "").strip()
            if name:
                mapping[name.lower()] = col_idx + 1  # 1-based
        return mapping

    def find_next_empty_row_in_column(self, col_idx, start_row=4):
        """Tìm hàng trống đầu tiên trong cột col_idx (1-based), bắt đầu từ start_row."""
        sheet = self._worksheet("LIST LƯU TẠM")
        col_letter = gspread.utils.rowcol_to_a1(1, col_idx)[0]
        # Đọc giá trị cột từ start_row
        col_values = sheet.col_values(col_idx)
        # col_values[start_row-1:] là từ hàng start_row
        for i in range(start_row - 1, len(col_values)):
            if not col_values[i].strip():
                return i + 1  # 1-based row
        # Không còn hàng trống trong dữ liệu đã đọc -> ghi tiếp hàng kế tiếp
        return len(col_values) + 1

    def append_creator(self, product, username):
        """Ghi username vào cột của sản phẩm tương ứng trong LIST LƯU TẠM.
        Chỉ ghi username vào đúng cột sản phẩm, không tràn sang cột khác."""
        col_map = self.get_product_column_map()
        col_idx = col_map.get(product.strip().lower())
        if col_idx is None:
            print(f"   ⚠ Không tìm thấy cột cho sản phẩm '{product}' trong LIST LƯU TẠM.")
            return False

        row = self.find_next_empty_row_in_column(col_idx)
        sheet = self._worksheet("LIST LƯU TẠM")
        sheet.update_cell(row, col_idx, username)
        return True

    # ------------------------------------------------------------------ #
    # Chuẩn hóa / parse số liệu
    # ------------------------------------------------------------------ #
    normalize_username = staticmethod(creator_rules.normalize_username)
    parse_compact_number = staticmethod(creator_rules.parse_compact_number)
    parse_follower_rule = staticmethod(creator_rules.parse_follower_rule)
    parse_min_rule = staticmethod(creator_rules.parse_min_rule)

    def validate_creator(self, creator, sku):
        return creator_rules.validate_creator(creator, sku)

    # Chunking cho phép tối đa 50 creator cho một lời mời cộng tác
    def chunk_list(self, lst, batch_size=50):
        """Chia danh sách thành các nhóm tối đa batch_size phần tử"""
        for i in range(0, len(lst), batch_size):
            yield lst[i:i + batch_size]

    def load_invitation_templates(self):
        """
        Đọc tab 'NỘI DUNG LỜI MỜI' theo cấu trúc thực tế (SKU ID ở Dòng 2, Nội dung ở các dòng bên dưới)
        Trả về dict dạng: {'1731921001118140226': 'Nội dung mẫu...', '1735397877631452994': 'Nội dung mẫu...'}
        """
        try:
            sheet = self._worksheet("NỘI DUNG LỜI MỜI")
            rows = sheet.get_all_values()
            
            if len(rows) < 3:
                return {}

            # Dòng 2 (index 1 trong Python) chứa các SKU ID
            sku_row = rows[1]
            
            templates = {}

            # Duyệt qua từng cột từ cột B (index 1) đến hết
            for col_idx in range(1, len(sku_row)):
                raw_skus = sku_row[col_idx].strip()
                if not raw_skus:
                    continue

                # Tách các SKU ID nếu một cột chứa nhiều SKU phân cách bởi dấu ';'
                sku_list = [s.strip() for s in raw_skus.split(";") if s.strip()]

                # Gom các mẫu nội dung có sẵn ở các dòng bên dưới (Dòng 3 -> Dòng 7, index 2 -> 6)
                content_samples = []
                for row_idx in range(2, min(7, len(rows))):
                    cell_val = rows[row_idx][col_idx].strip() if col_idx < len(rows[row_idx]) else ""
                    if cell_val:
                        content_samples.append(cell_val)

                # Chọn mẫu lời mời (Lấy mẫu đầu tiên ở Dòng 3 làm mặc định)
                selected_template = content_samples[0] if content_samples else ""

                # Gán mẫu lời mời cho tất cả các SKU ID thuộc cột này
                for sku_id in sku_list:
                    templates[sku_id] = selected_template

            return templates

        except Exception as e:
            diagnostics.log_exception("Không đọc được mẫu nội dung lời mời", e)
            print(f"   ⚠ Không thể đọc tab 'NỘI DUNG LỜI MỜI': {e}")
            return {}

    def log_invitation_history(self, invitation_name, total_creators, total_follow):
        """Ghi một dòng vào tab 'THEO DÕI LỜI MỜI' đúng theo cột A-G."""
        try:
            ws = self._worksheet("THEO DÕI LỜI MỜI")

            today = datetime.datetime.now()
            expiry = today + datetime.timedelta(days=30)
            stt = len([v for v in ws.col_values(1)[1:] if v.strip()]) + 1

            ws.append_row(
                [
                    stt,                                # A: STT
                    invitation_name,                    # B: Tên lời mời
                    total_creators,                     # C: Số KOL/KOC
                    today.strftime("%d/%m/%Y"),         # D: Ngày gửi
                    expiry.strftime("%d/%m/%Y"),        # E: Có hiệu lực đến
                    total_follow,                       # F: Follow-up đã gửi
                    today.strftime("%d/%m/%Y") if total_follow else "",  # G
                ],
                value_input_option="USER_ENTERED",
            )
        except Exception as e:
            diagnostics.log_exception("Không ghi được lịch sử lời mời lên Sheet", e)
            print(f"     ⚠️ Không ghi được lịch sử lên Google Sheet: {e}")
            raise

    def update_followup_history(self, invitation_name, total_follow):
        """Cập nhật F-G của duy nhất dòng khớp tên lời mời, giữ nguyên A-E."""
        ws = self._worksheet("THEO DÕI LỜI MỜI")
        matching_rows = [
            row for row, name in enumerate(ws.col_values(2), start=1)
            if name.strip() == invitation_name
        ]
        if len(matching_rows) != 1:
            raise RuntimeError(
                f"Lời mời '{invitation_name}' có {len(matching_rows)} dòng lịch sử; "
                "không cập nhật follow-up để tránh sửa nhầm."
            )
        row = matching_rows[0]
        ws.update(
            range_name=f"F{row}:G{row}",
            values=[[total_follow, datetime.datetime.now().strftime("%d/%m/%Y")]],
            value_input_option="USER_ENTERED",
        )
