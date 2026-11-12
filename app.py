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

        invitation_templates = sheet_mgr.load_invitation_templates()    

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
                if not bot.apply_category_filter(cat):
                    print(f"   -> Bỏ qua hạng mục không tìm thấy: {cat}")

            # Bộ lọc followers đọc từ 'YÊU CẦU FOLLOWERS' (vd '1000<Followers<30000')
            fmin, fmax = sheet_mgr.parse_follower_rule(sku["followers_rule"])
            if fmin is not None:
                if not bot.apply_follower_filter(fmin, fmax):
                    raise RuntimeError("Chưa áp dụng được bộ lọc followers")



            sku_count = 0
            creators_for_this_sku = [] # Mảng lưu creator trong RAM

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

                    # ĐƯA VÀO LIST TRONG RAM ĐỂ TẠO LỜI MỜI
                    creators_for_this_sku.append(c["username"])

                    sku_count += 1
                    grand_total += 1
                    print(f"   [+] Đã ghi Sheet & RAM: {c['username']} | followers={c['followers']} | "
                          f"GMV={c['gmv']} | số món={c['orders']} (SKU {sku_count}/{target}, tổng {grand_total})")
                    time.sleep(MIN_DELAY)

            print(f"   → Hoàn tất SKU '{product}': {sku_count}/{target} creator.")


            # =========================================================================
            # TẠO LỜI MỜI (CHIA ĐỢT TỐI ĐA 50 NGƯỜI)
            # =========================================================================
            if creators_for_this_sku:
                print(f"\n🚀 Bắt đầu tạo lời mời cho SKU: {product} (Tổng {len(creators_for_this_sku)} người)...")

                # Điều hướng sang trang Cộng tác mục tiêu
                bot.go_to_target_collaboration()

                # Chia nhỏ danh sách thành các đợt tối đa 50 người (Chuẩn theo SOP Auto.md)[cite: 2, 3]
                creator_batches = list(sheet_mgr.chunk_list(creators_for_this_sku, batch_size=50))
                invite_content = invitation_templates.get(sku['sku_id'], "")

                #vòng lặp tạo lời mời cho từng đợt (_1, _2...)[cite: 3]
                for batch_index, batch_creators in enumerate(creator_batches, start=1):
                    print(f"\n--- Đang xử lý ĐỢT {batch_index}/{len(creator_batches)} ({len(batch_creators)} creators) ---")

                    success, inv_name, total_sent = bot.create_target_invitation(
                        sku_info=sku,
                        invite_content=invite_content,
                        creator_usernames=batch_creators,
                        batch_index=batch_index,
                    )


                    ######################################################################
                    # GỬI TIN NHẮN CHO CREATOR
                    ######################################################################
                    if not success:
                        raise RuntimeError(
                            f"Đợt {batch_index} chưa xác minh gửi thành công. "
                            "Dừng tại đây; kiểm tra bản nháp/lịch sử trước khi chạy lại."
                        )

                    # Ghi lời mời đã xác minh trước, không phụ thuộc kết quả chat.
                    sheet_mgr.log_invitation_history(
                        invitation_name=inv_name,
                        total_creators=total_sent,
                        total_follow=0,
                    )
                    try:
                        if not bot.share_invitation_via_chat():
                            raise RuntimeError("Chat chưa xác nhận gửi đủ; giữ trạng thái để kiểm tra.")
                    except Exception as e:
                        print(f"   ⚠️ Không chia sẻ được lời mời '{inv_name}' qua chat: {e}")
                        raise
                    sheet_mgr.update_followup_history(inv_name, total_sent)
                    print(f"   ✓ Follow-up '{inv_name}': {total_sent} creator (gán theo tổng đã mời).")

            else:
                print(f"⚠️ SKU '{product}' không có creator nào đạt điều kiện để tạo lời mời.")

        print(f"\n=== [HOÀN TẤT] Tổng {grand_total} creator mới ===")

    except Exception as e:
        print(f"Đã xảy ra lỗi trong quá trình chạy: {e}")
    # finally:
    #     bot.close()


if __name__ == "__main__":
    main()
