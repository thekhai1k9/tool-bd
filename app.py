import time
from sheet_helper import GoogleSheetManager
from browser_helper import TikTokBrowserAutomation

CREDENTIALS_FILE = "credentials.json"
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1ZmU9BO7uX8BDpOrdEylbhnNmxUSuZjm7rlsWlNk5LwI/edit?pli=1&gid=0#gid=0"

MIN_DELAY = 5        # nghỉ tối thiểu giữa mỗi creator đã ghi


def main():
    print("--- [TASK 1] KHỞI ĐỘNG HỆ THỐNG TỰ ĐỘNG ---")

    try:
        sheet_mgr = GoogleSheetManager(CREDENTIALS_FILE, SPREADSHEET_URL)
        skus = sheet_mgr.load_skus()
        print("==============??? sku", skus)
        keywords_by_product = sheet_mgr.load_keywords()
        blacklist = sheet_mgr.load_blacklist()
        existing = sheet_mgr.load_existing_creators()
        kw_lookup = {k.strip().lower(): v for k, v in keywords_by_product.items()}
        print(f"-> {len(skus)} SKU, {len(keywords_by_product)} nhóm keyword, "
              f"{len(blacklist)} blacklist, {len(existing)} creator đã lưu.")
    except Exception as e:
        print(f"Lỗi kết nối hoặc đọc Google Sheet: {e}")
        return

    bot = TikTokBrowserAutomation()
    grand_total = 0

    try:
        bot.start_browser()
        bot.wait_for_user_login()
        _, current_shop_name = bot.check_current_shop()

        if not current_shop_name: 
            print("   ❌ Không xác định được Shop đang đăng nhập. Dừng tool!")
            return
        print(f"\n🚀 Đang chạy automation cho Shop: {current_shop_name} (Tên Shop: {current_shop_name})")

        shop_key = current_shop_name.strip().lower()

        for sku in skus:
            product = sku["product"]
            target = sku["target"]
            keywords = kw_lookup.get(product.strip().lower())
            sku_shop = str(sku.get("shop", "")).strip().lower()
            
            print("=====shop_key và product", sku["shop"], shop_key)
            if not keywords:
                print(f"-> Bỏ qua '{product}': không có keyword trong LIST KEYWORD.")
                continue

            is_shop_match = (shop_key in sku_shop) or (sku_shop in shop_key)
            if not is_shop_match:
                print(f"-> Bỏ qua SKU '{product}': Shop đang đăng nhập '{current_shop_name}' không trùng với shop trong list CMS SKU: '{sku.get('shop')}'")
                continue

            print(f"\n=== SKU: {product} (ID {sku['sku_id']}) | mục tiêu {target} creators | "
                  f"followers={sku['followers_rule']} | GMV={sku['gmv_rule']} | số món={sku['orders_rule']} ===")

            # Bộ lọc hạng mục đọc từ cột 'NGÀNH HÀNG / HẠNG MỤC KOL/KOC'
            bot.reset_filters()
            for cat in sku["categories"]:
                bot.apply_category_filter(cat)

            # Bộ lọc followers đọc từ 'YÊU CẦU FOLLOWERS' (vd '1000<Followers<30000')
            fmin, fmax = sheet_mgr.parse_follower_rule(sku["followers_rule"])
            if fmin is not None:
                bot.apply_follower_filter(fmin, fmax)
            else:
                print("   -> Không có rule followers, bỏ qua lọc follower.")

            sku_count = 0
            for kw in keywords:
                if sku_count >= target:
                    break

                creators = bot.collect_creators_for_keyword(kw)
                for c in creators:
                    if sku_count >= target:
                        break

                    norm = sheet_mgr.normalize_username(c["username"])
                    if not norm:
                        continue
                    # Chống ghi trùng: blacklist + LIST LƯU TẠM + đã ghi trong lượt này
                    if norm in blacklist or norm in existing:
                        continue

                    ok, reasons = sheet_mgr.validate_creator(c, sku)
                    if not ok:
                        print(f"   [-] Loại {c['username']}: {'; '.join(reasons)}")
                        continue

                    # Chỉ ghi username vào cột của sản phẩm tương ứng (không tràn cột khác)
                    success = sheet_mgr.append_creator(product, c["username"])
                    if not success:
                        continue
                    existing.add(norm)
                    sku_count += 1
                    grand_total += 1
                    print(f"   [+] Ghi {c['username']} | followers={c['followers']} | "
                          f"GMV={c['gmv']} | số món={c['orders']} (SKU {sku_count}/{target}, tổng {grand_total})")
                    time.sleep(MIN_DELAY)

            print(f"   → Hoàn tất SKU '{product}': {sku_count}/{target} creator.")

        print(f"\n=== [HOÀN TẤT] Tổng {grand_total} creator mới ===")

    except Exception as e:
        print(f"Đã xảy ra lỗi trong quá trình chạy: {e}")
    finally:
        bot.close()


if __name__ == "__main__":
    main()
