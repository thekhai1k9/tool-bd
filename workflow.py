"""Per-SKU orchestration; browser, Sheet and checkpoint policies stay in their adapters."""
from dataclasses import dataclass
import diagnostics
import creator_rules
from search_progress import DailyProgress, build_search_terms


@dataclass
class RunSources:
    keywords: dict
    english_keywords: dict
    existing: set
    invitations: dict


class BookingWorkflow:
    def __init__(self, sheet_mgr, bot, shop_name, creator_search_url, sources):
        self.sheet_mgr = sheet_mgr
        self.bot = bot
        self.shop_name = shop_name
        self.creator_search_url = creator_search_url
        self.sources = sources

    def process_sku(self, sku, grand_total):
        sheet_mgr, bot = self.sheet_mgr, self.bot
        current_shop_name = self.shop_name
        shop_key = current_shop_name.strip().lower()
        creator_search_url = self.creator_search_url
        kw_lookup, en_kw_lookup = self.sources.keywords, self.sources.english_keywords
        existing = self.sources.existing
        product = sku["product"]
        target = sku["target"]
        keywords = kw_lookup.get(product.strip().lower(), [])
        english_keywords = en_kw_lookup.get(product.strip().lower(), [])
        sku_shop = str(sku.get("shop", "")).strip().lower()
        diagnostics.set_context(sku=sku["sku_id"], batch=None, keyword=None, creator=None, stage="sku_setup")

        is_shop_match = (shop_key in sku_shop) or (sku_shop in shop_key)
        if not is_shop_match:
            print(f"-> Bỏ qua SKU '{product}': Shop đang đăng nhập '{current_shop_name}' không trùng với shop trong list CMS SKU: '{sku.get('shop')}'")
            return grand_total

        progress = DailyProgress(current_shop_name, sku["sku_id"])
        diagnostics.set_context(stage="checkpoint")
        if not progress.path.exists():
            print("   -> Checkpoint mới: số đã gửi DAILY chỉ tính các đợt được bản code này ghi nhận.")
        if progress.blocking_batches:
            self._resume_sent_chats(progress)
        sent_today = len(progress.sent_usernames)
        if sent_today >= target:
            print(f"-> SKU '{product}' đã gửi {sent_today}/{target} hôm nay, bỏ qua.")
            return grand_total

        if not keywords and not english_keywords:
            print(f"-> Bỏ qua '{product}': không có keyword trong LIST KEYWORD hoặc LIST KEYWORD EN.")
            return grand_total

        criteria = {key: sku[key] for key in ("followers_rule", "gmv_rule", "orders_rule", "categories")}
        if progress.data.get("criteria") != criteria:
            previous_criteria = progress.data.get("criteria")
            if previous_criteria and set(previous_criteria["categories"]) != set(criteria["categories"]):
                invalidated = progress.data.setdefault("invalidated", {})
                for username in progress.pending_usernames:
                    invalidated[username] = {
                        **progress.data["selected"].pop(username),
                        "reason": "Hạng mục CMS SKU đã thay đổi; không tái sử dụng lựa chọn cũ.",
                    }
                print("   -> Hạng mục đã đổi: bỏ lựa chọn chưa gửi từ bộ lọc cũ, giữ lịch sử.")
            progress.data.update(criteria=criteria, scanned={}, finished_keywords=[])
            progress.save()

        # Recheck exclusions from the old combined duplicate rule, without resetting send history.
        reopened_keywords = set()
        for keyword, scanned in progress.data["scanned"].items():
            legacy_names = [name for name, creator in scanned.items() if any(
                reason.startswith("trùng ") and reason != "trùng LIST LƯU TẠM/lượt hiện tại"
                for reason in creator.get("reasons", [])
            )]
            for name in legacy_names:
                del scanned[name]
            if legacy_names:
                reopened_keywords.add(keyword.casefold())
        if reopened_keywords:
            progress.data["finished_keywords"] = [
                keyword for keyword in progress.data["finished_keywords"]
                if keyword.casefold() not in reopened_keywords
            ]
            progress.save()
            print("   -> Kiểm tra lại creator bị loại theo quy tắc chống trùng cũ; giữ lịch sử gửi.")

        # Khôi phục người đã chọn nhưng chưa gửi, kể cả đã có trong LIST LƯU TẠM.
        for username in list(progress.pending_usernames):
            creator = progress.data["selected"][username]
            valid, reasons = creator_rules.validate_creator(creator, sku)
            if not valid:
                print(f"   [-] Bỏ checkpoint {username}: {reasons}")
                del progress.data["selected"][username]
                progress.save()
                continue
            if not creator.get("sheet_saved"):
                if username not in existing and not sheet_mgr.append_creator(product, creator["username"]):
                    raise RuntimeError(f"Chưa lưu được checkpoint creator {username} vào Sheet.")
                creator["sheet_saved"] = True
                progress.save()
            existing.add(username)
        existing.update(progress.sent_usernames)

        print(f"\n=== SKU: {product} (ID {sku['sku_id']}) | mục tiêu {target} creators | "
              f"followers={sku['followers_rule']} | GMV={sku['gmv_rule']} | số món={sku['orders_rule']} ===")

        if bot.page.url != creator_search_url:
            bot.page.goto(creator_search_url)
            bot.find_search_input()

        # Bộ lọc hạng mục đọc từ cột 'NGÀNH HÀNG / HẠNG MỤC KOL/KOC'
        diagnostics.set_context(stage="filters")
        bot.reset_filters()
        for cat in sku["categories"]:
            if not bot.apply_category_filter(cat):
                print(f"   -> Bỏ qua hạng mục không tìm thấy: {cat}")

        # Bộ lọc followers đọc từ 'YÊU CẦU FOLLOWERS' (vd '1000<Followers<30000')
        fmin, fmax = creator_rules.parse_follower_rule(sku["followers_rule"])
        if fmin is not None:
            if not bot.apply_follower_filter(fmin, fmax):
                raise RuntimeError("Chưa áp dụng được bộ lọc followers")



        sku_count, grand_total = self.collect_creators(
            sku, progress, sent_today, keywords, english_keywords, grand_total,
        )

        print(f"   → Hoàn tất SKU '{product}': {sku_count}/{target} creator.")

        if sku_count < target:
            print(
                f"⚠️ SKU '{product}' thiếu {target - sku_count} creator sau khi duyệt "
                f"keyword/brand/biến thể. Chưa tạo/gửi lời mời; checkpoint: {progress.path}. "
                "Bổ sung keyword trong LIST KEYWORD hoặc LIST KEYWORD EN rồi chạy tiếp."
            )
            return grand_total
        creators_for_this_sku = [
            progress.data["selected"][name]["username"]
            for name in progress.pending_usernames[:target - sent_today]
        ]


        # =========================================================================
        # TẠO LỜI MỜI (CHIA ĐỢT TỐI ĐA 50 NGƯỜI)
        # =========================================================================
        self.send_batches(sku, progress, creators_for_this_sku)
        return grand_total

    def collect_creators(self, sku, progress, sent_today, keywords, english_keywords, grand_total):
        sheet_mgr, bot = self.sheet_mgr, self.bot
        product, target = sku["product"], sku["target"]
        existing = self.sources.existing
        sku_count = sent_today + len(progress.pending_usernames)
        search_terms = build_search_terms(keywords, product, english_keywords)
        print(
            f"   -> DAILY: đã gửi {sent_today}, chờ gửi {len(progress.pending_usernames)}, "
            f"cần tìm thêm {max(0, target - sku_count)}. "
            f"{len(search_terms)} keyword/brand/biến thể."
        )

        for kw in search_terms:
            if sku_count >= target:
                break
            if any(done.casefold() == kw.casefold() for done in progress.data["finished_keywords"]):
                continue

            diagnostics.set_context(keyword=kw, creator=None, stage="discover_creators")
            scan_key = next((key for key in progress.data["scanned"] if key.casefold() == kw.casefold()), kw)
            scanned = progress.data["scanned"].setdefault(scan_key, {})
            creators = bot.iter_creators_for_keyword(kw, set(scanned))
            keyword_finished = True
            for c in creators:
                diagnostics.set_context(creator=c["username"])
                norm = creator_rules.normalize_username(c["username"])
                if not norm:
                    continue
                ok, reasons = creator_rules.validate_creator(c, sku)
                if norm in existing:
                    reasons.append("trùng LIST LƯU TẠM/lượt hiện tại")
                if c.get("already_invited"):
                    reasons.append("TikTok hiển thị đã mời hoặc không thể mời")
                scanned[norm] = {**c, "reasons": reasons}
                if not ok or reasons:
                    progress.save()
                    print(f"   [-] Loại {c['username']}: {'; '.join(reasons)}")
                    continue

                # Lưu trước khi gọi Sheet để khôi phục được cả khi mạng/tiến trình lỗi.
                progress.data["selected"][norm] = {**c, "sheet_saved": False}
                progress.save()
                if not sheet_mgr.append_creator(product, c["username"]):
                    raise RuntimeError(f"Không ghi được creator {c['username']} vào Sheet; đã giữ checkpoint.")
                progress.data["selected"][norm]["sheet_saved"] = True
                progress.save()
                existing.add(norm)

                sku_count += 1
                grand_total += 1
                print(f"   [+] Đã ghi Sheet & RAM: {c['username']} | followers={c['followers']} | "
                      f"GMV={c['gmv']} | số món={c['orders']} (SKU {sku_count}/{target}, tổng {grand_total})")
                if sku_count >= target:
                    keyword_finished = False
                    creators.close()
                    break
            if keyword_finished:
                progress.data["finished_keywords"].append(kw)
                progress.save()

        return sku_count, grand_total

    def send_batches(self, sku, progress, creators_for_this_sku):
        sheet_mgr, bot = self.sheet_mgr, self.bot
        product, target = sku["product"], sku["target"]
        invitation_templates = self.sources.invitations
        if creators_for_this_sku:
            print(f"\n🚀 Bắt đầu tạo lời mời cho SKU: {product} (Tổng {len(creators_for_this_sku)} người)...")

            creator_batches = progress.prepare_batches(target, batch_size=50)
            invite_content = invitation_templates.get(sku['sku_id'], "")

            for batch_state in creator_batches:
                batch_index = batch_state["index"]
                diagnostics.set_context(batch=batch_index, keyword=None, creator=None, stage="target_navigation")
                batch_creators = [progress.data["selected"][name]["username"] for name in batch_state["usernames"]]
                print(f"\n--- Đang xử lý ĐỢT {batch_index} ({len(batch_creators)} creators) ---")
                if not bot.go_to_target_collaboration():
                    raise RuntimeError("Không vào được Cộng tác mục tiêu; danh sách đã lưu checkpoint.")

                batch_state.update(
                    status="draft", stage="configure_invitation", error=None,
                    attempt=batch_state.get("attempt", 1) + 1,
                )
                progress.save()

                def save_batch_state(update, state=batch_state):
                    state.update(update)
                    progress.save()

                success, inv_name, total_sent = bot.create_target_invitation(
                    sku_info=sku,
                    invite_content=invite_content,
                    creator_usernames=batch_creators,
                    batch_index=batch_index,
                    on_state_change=save_batch_state,
                    attempt=batch_state["attempt"],
                )


                ######################################################################
                # GỬI TIN NHẮN CHO CREATOR
                ######################################################################
                if not success:
                    if batch_state["status"] in ("draft", "ready"):
                        raise RuntimeError(
                            f"Đợt {batch_index} dừng ở bước {batch_state['stage']}; CHƯA BẤM GỬI. "
                            f"{batch_state.get('error') or ''} "
                            "Danh sách đã giữ trong checkpoint; chạy lại sẽ cấu hình lại từ danh sách này."
                        )
                    raise RuntimeError(
                        f"Đợt {batch_index}, trạng thái {batch_state['status']}, bước {batch_state['stage']}: "
                        f"{batch_state.get('error') or 'Cần đối chiếu kết quả sau thao tác Gửi.'} "
                        "Dừng tại đây; kiểm tra bản nháp/lịch sử trước khi chạy lại."
                    )

                batch_state.update(status="sent", stage="log_history", invitation_name=inv_name, total_sent=total_sent)
                diagnostics.set_context(stage="log_history")
                progress.save()

                # Ghi lời mời đã xác minh trước, không phụ thuộc kết quả chat.
                sheet_mgr.log_invitation_history(
                    invitation_name=inv_name,
                    total_creators=total_sent,
                    total_follow=0,
                )
                self._finish_batch_chat(progress, batch_state, batch_creators)

        else:
            print(f"⚠️ SKU '{product}' không có creator nào đạt điều kiện để tạo lời mời.")


    def _finish_batch_chat(self, progress, batch_state, batch_creators, chat_url=None, cached_result=None):
        sheet_mgr, bot = self.sheet_mgr, self.bot
        inv_name, batch_index = batch_state["invitation_name"], batch_state["index"]
        try:
            batch_state["stage"] = "chat"
            diagnostics.set_context(stage="chat")
            progress.save()
            def save_chat_result(result):
                batch_state["chat_result"] = result
                progress.save()

            if cached_result is not None:
                chat_result = cached_result
            elif chat_url is not None:
                chat_result = bot.share_invitation_via_chat(batch_creators, on_result=save_chat_result, chat_url=chat_url)
            else:
                chat_result = bot.share_invitation_via_chat(batch_creators, on_result=save_chat_result)
            save_chat_result(chat_result)
            if chat_result.get("confirmed") is not True:
                raise RuntimeError("Chat chưa xác nhận gửi đủ; giữ trạng thái để kiểm tra.")
            expected = {creator_rules.normalize_username(name) for name in batch_creators}
            selected = chat_result["selected_usernames"]
            rate_limit = chat_result["rate_limit_usernames"]
            if (len(set(selected)) != len(selected) or len(set(rate_limit)) != len(rate_limit)
                    or set(selected) & set(rate_limit) or set(selected) | set(rate_limit) != expected
                    or chat_result["followup_count"] != len(selected)):
                raise RuntimeError("Kết quả chat không khớp danh sách đợt; chưa cập nhật Sheet.")
        except Exception as e:
            diagnostics.capture_error(bot.page, e)
            batch_state["error"] = str(e)
            progress.save()
            print(f"   ⚠️ Không chia sẻ được lời mời '{inv_name}' qua chat: {e}")
            raise
        diagnostics.set_context(stage="update_followup_history")
        batch_state["stage"] = "update_followup_history"
        progress.save()
        sheet_mgr.update_followup_history(inv_name, chat_result["followup_count"], rate_limit)
        batch_state.update(status="completed", stage="done", error=None)
        progress.save()
        diagnostics.set_context(stage="done")
        print(f"   ✓ Follow-up '{inv_name}': {chat_result['followup_count']} creator; "
              f"rate limit: {len(rate_limit)} (theo lựa chọn chat và xác nhận người dùng).")

    def _resume_sent_chats(self, progress):
        batches = progress.blocking_batches
        # Do not resume any sends while another batch has an uncertain invitation result.
        for batch in batches:
            if batch['status'] != 'sent' or batch.get('stage') not in ('chat', 'update_followup_history'):
                raise RuntimeError(
                    f"Đợt {batch['index']} đang {batch['status']} ở bước {batch.get('stage', 'không rõ')}. "
                    f"Kiểm tra lịch sử trước; không tự gửi lại. Checkpoint: {progress.path}"
                )
        for batch in batches:
            name = batch.get('invitation_name')
            names = batch.get('usernames', [])
            if not name or not names or len(set(names)) != len(names):
                raise RuntimeError('Checkpoint thiếu tên lời mời hoặc danh sách creator; không tự khôi phục chat.')
            result = batch.get('chat_result', {})
            diagnostics.set_context(batch=batch['index'], stage='chat_resume', keyword=None, creator=None)
            print(f"   -> Khôi phục Đợt {batch['index']}: {name}; giữ lời mời đã gửi.")
            if result.get('confirmed') is True:
                self._finish_batch_chat(progress, batch, names, cached_result=result)
                continue
            if result.get('share_clicked') is True:
                raise RuntimeError('Đã thao tác Chia sẻ nhưng chat chưa xác nhận; kiểm tra TikTok trước, không tự gửi lại.')
            if result.get('share_clicked') is not False:
                answer = input(
                    f"Đợt {batch['index']} ({name}) chưa lưu trạng thái chat. "
                    "Chỉ nếu chắc chắn CHƯA bấm Chia sẻ, nhập 'CHUA CHIA SE' để tiếp tục; Enter để dừng: "
                ).strip()
                if answer != 'CHUA CHIA SE':
                    raise RuntimeError('Chưa xác minh chat chưa gửi; giữ checkpoint, không tự gửi lại.')
            chat_url = result.get('chat_url')
            if not chat_url:
                chat_url = input(
                    f"Mở trang chat của đúng lời mời '{name}', dán URL có plan_id và shop_id "
                    "(không tạo lời mời mới); Enter để dừng: "
                ).strip()
            if not chat_url:
                raise RuntimeError('Chưa có URL chat đúng lời mời; giữ checkpoint.')
            self._finish_batch_chat(progress, batch, names, chat_url=chat_url)
