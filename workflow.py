"""Per-SKU orchestration; browser, Sheet and checkpoint policies stay in their adapters."""
from dataclasses import dataclass, field
import followup
from itertools import islice
import diagnostics
import creator_rules
from search_progress import DailyProgress, build_search_terms

GMV_BUCKETS = [
    ("0-50K₫",      50_000),
    ("50K₫-100K₫",  100_000),
    ("100K₫-500K₫", 500_000),
    ("500K₫-1M₫",   1_000_000),
    ("1M₫+",        None),
]

ORDER_BUCKETS = [
    ("0-10",      10),
    ("10-100",    100),
    ("100-1.000", 1_000),
    ("1.000+",    None),
]


@dataclass
class RunSources:
    keywords: dict
    english_keywords: dict
    existing: set
    invitations: dict
    followups: dict = field(default_factory=dict)

def choose_buckets(minimum, buckets):
    if minimum is None:
        return []

    return [
        label
        for label, upper in buckets
        if upper is None or upper > minimum
    ]

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

        # Kiểm tra mẫu trước khi tìm/gửi; từng người sẽ dùng snapshot trong checkpoint.
        followup.render_message(self.sources.followups.get(str(sku["sku_id"])), {"username": "creator"})

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
            progress.data.update(criteria=criteria, scanned={}, finished_keywords=[],
                                 search_round=1, keyword_progress={})
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

        # Bộ lọc hạng mục đọc từ cột 'NGÀNH HÀNG / HẠNG MỤC KOL/KOC / GMV / SỐ MÓN BÁN RA'
        self.apply_sku_filters(sku)

        sku_count, grand_total = self.collect_creators(
            sku, progress, sent_today, keywords, english_keywords, grand_total,
        )

        print(f"   → Kết quả tìm SKU '{product}': {sku_count}/{target} creator.")

        if sku_count < target:
            print(
                f"⚠️ SKU '{product}' thiếu {target - sku_count} creator sau khi duyệt "
                f"keyword/brand/biến thể. Chưa tạo/gửi lời mời; checkpoint: {progress.path}. "
                "Giữ checkpoint rồi chạy lại để thử nguồn cũ; có thể bổ sung LIST KEYWORD/LIST KEYWORD EN."
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

    def apply_sku_filters(self, sku):
        bot = self.bot
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

        # Bộ lọc gmv từ cms sku
        gmin = creator_rules.parse_min_rule(sku["gmv_rule"])
        bot.apply_performance_filter(
            "GMV",
            choose_buckets(gmin, GMV_BUCKETS),
        )
        # Bộ lọc số món bán ra từ cms sku
        omin = creator_rules.parse_min_rule(sku["orders_rule"])
        bot.apply_performance_filter(
            "Số món bán ra",
            choose_buckets(omin, ORDER_BUCKETS),
        )


    def collect_creators(self, sku, progress, sent_today, keywords, english_keywords, grand_total):
        target = sku["target"]
        while sent_today + len(progress.pending_usernames) < target:
            before = len(progress.pending_usernames)
            round_number = progress.data["search_round"]
            print(f"   -> Vòng tìm {round_number}: tối đa {100 * 2 ** min(round_number - 1, 2)} creator mới/keyword.")
            count, grand_total = self._collect_creator_round(
                sku, progress, sent_today, keywords, english_keywords, grand_total,
            )
            if count >= target:
                return count, grand_total
            progress.data["search_round"] = round_number + 1
            progress.save()
            if len(progress.pending_usernames) == before:
                print("   -> Cả vòng không thêm creator đạt yêu cầu; giữ checkpoint để lần sau thử lại.")
                break
        return sent_today + len(progress.pending_usernames), grand_total

    def _collect_creator_round(self, sku, progress, sent_today, keywords, english_keywords, grand_total):
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

        # Chưa quét trước, sau đó ưu tiên keyword có nhiều người đạt.
        states = progress.data["keyword_progress"]
        round_number = progress.data["search_round"]
        budget = 100 * 2 ** min(round_number - 1, 2)
        search_terms.sort(key=lambda kw: (
            kw in states,
            -states.get(kw, {}).get("qualified_count", 0),
        ))
        for kw in search_terms:
            if sku_count >= target:
                break
            if states.get(kw, {}).get("round") == round_number and states[kw].get("status") != "running":
                continue

            diagnostics.set_context(keyword=kw, creator=None, stage="discover_creators")
            scan_key = next((key for key in progress.data["scanned"] if key.casefold() == kw.casefold()), kw)
            scanned = progress.data["scanned"].setdefault(scan_key, {})
            creators = bot.iter_creators_for_keyword(kw, set(scanned))
            state = progress.update_keyword(
                kw, round=round_number, status="running", stop_reason=None, error_type=None,
                new_scan_budget=budget, round_scanned_count=(
                    states.get(kw, {}).get("round_scanned_count", 0)
                    if states.get(kw, {}).get("round") == round_number else 0
                ), scanned_count=len(scanned),
                qualified_count=states.get(kw, {}).get("qualified_count", 0),
            )
            stop_reason = "no_new_results"
            try:
                for c in islice(creators, max(0, budget - state["round_scanned_count"])):
                    diagnostics.set_context(creator=c["username"])
                    norm = creator_rules.normalize_username(c["username"])
                    if not norm:
                        continue
                    ok, reasons = creator_rules.validate_creator(c, sku)
                    if norm in existing:
                        reasons.append("trùng LIST LƯU TẠM/lượt hiện tại")
                    if c.get("already_invited"):
                        reasons.append("TikTok hiển thị đã mời hoặc không thể mời")
                    if norm in progress.data["invitation_conflicts"]:
                        reasons.append("Trùng lặp lời mời được TikTok xác nhận trong checkpoint hôm nay")
                    scanned[norm] = {**c, "reasons": reasons}
                    state.update(round_scanned_count=state["round_scanned_count"] + 1,
                                 scanned_count=len(scanned), last_scanned_username=norm)
                    progress.update_keyword(kw, **state)
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
                    progress.update_keyword(kw, qualified_count=state["qualified_count"] + 1)
                    print(f"   [+] Đã ghi Sheet & RAM: {c['username']} | followers={c['followers']} | "
                          f"GMV={c['gmv']} | số món={c['orders']} (SKU {sku_count}/{target}, tổng {grand_total})")
                    if sku_count >= target:
                        stop_reason = "daily_reached"
                        break
                if stop_reason != "daily_reached" and state["round_scanned_count"] >= budget:
                    stop_reason = "scan_budget_reached"
            except BaseException as error:
                progress.update_keyword(
                    kw, status="running", stop_reason="interrupted" if isinstance(error, KeyboardInterrupt)
                    else "scan_failed", error_type=type(error).__name__,
                )
                raise
            finally:
                creators.close()
            progress.update_keyword(
                kw, status="paused" if stop_reason == "scan_budget_reached" else "temporary_exhausted"
                if stop_reason == "no_new_results" else "completed", stop_reason=stop_reason,
            )

        return sku_count, grand_total

    def replace_invitation_conflicts(self, sku, progress, batch, conflicts):
        names = {creator_rules.normalize_username(name) for name in conflicts}
        expected = set(batch["usernames"])
        if not names or not names <= expected or batch["status"] not in ("draft", "ready"):
            raise RuntimeError("Danh sách trùng không khớp đợt chưa gửi; dừng để kiểm tra.")
        batch.setdefault("required_size", len(batch["usernames"]))
        for name in names:
            progress.data["invitation_conflicts"][name] = {
                "username": name, "status": "invitation_conflict", "reason": "Trùng lặp lời mời",
                "batch_index": batch["index"], "day": progress.data["day"],
            }
            progress.data["selected"].pop(name, None)
            self.sources.existing.add(name)
        batch["usernames"] = [name for name in batch["usernames"] if name not in names]
        batch.update(status="draft", stage="replace_creators")
        progress.save()
        reserved = {name for other in progress.data["batches"] if other is not batch
                    and other["status"] != "superseded" for name in other["usernames"]}

        def candidates():
            return [name for name in progress.pending_usernames
                    if name not in reserved and name not in batch["usernames"]]

        missing = batch["required_size"] - len(batch["usernames"])
        if len(candidates()) < missing:
            draft_page = self.bot.page
            search_page = draft_page.context.new_page()
            try:
                self.bot.page = search_page
                search_page.goto(self.creator_search_url, wait_until="domcontentloaded")
                self.bot.find_search_input()
                self.apply_sku_filters(sku)
                progress.data["search_round"] += 1
                progress.save()
                required_total = len(progress.sent_usernames) + len(progress.pending_usernames) + missing - len(candidates())
                self.collect_creators(
                    {**sku, "target": required_total}, progress, len(progress.sent_usernames),
                    self.sources.keywords.get(sku["product"].strip().lower(), []),
                    self.sources.english_keywords.get(sku["product"].strip().lower(), []), 0,
                )
            finally:
                self.bot.page = draft_page
                search_page.close()
                draft_page.bring_to_front()
        additions = candidates()[:missing]
        if len(additions) != missing:
            progress.save()
            raise RuntimeError(f"Chưa đủ người thay thế: cần {missing}, có {len(additions)}; giữ bản nháp/checkpoint.")
        batch["usernames"].extend(additions)
        progress.save()
        print(f"   [CONFLICT] Đợt {batch['index']}: loại {sorted(names)}, thay bằng {additions}.")
        return [progress.data["selected"][name]["username"] for name in batch["usernames"]]

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
                    on_creator_conflicts=lambda names: self.replace_invitation_conflicts(
                        sku, progress, batch_state, names,
                    ),
                )
                batch_creators = [progress.data["selected"][name]["username"] for name in batch_state["usernames"]]


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
        recipients = batch_state.get("followup", {}).get("recipients")
        if recipients is None:
            template = self.sources.followups.get(progress.data["sku_id"])
            recipients = {
                creator_rules.normalize_username(name): {
                    "status": "pending", "message_snapshot": followup.render_message(
                        template, progress.data["selected"][creator_rules.normalize_username(name)],
                    ),
                } for name in batch_creators
            }
            batch_state["followup"] = {"version": 1, "recipients": recipients}
            progress.save()
        if set(recipients) != {creator_rules.normalize_username(name) for name in batch_creators}:
            raise RuntimeError("Danh sách follow-up không khớp đợt; chưa gửi.")
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
                chat_result = bot.share_invitation_via_chat(batch_creators, on_result=save_chat_result, chat_url=chat_url, keep_open=True)
            else:
                chat_result = bot.share_invitation_via_chat(batch_creators, on_result=save_chat_result, keep_open=True)
            save_chat_result(chat_result)
            if chat_result.get("confirmed") is not True:
                raise RuntimeError("Chat chưa xác nhận gửi đủ; giữ trạng thái để kiểm tra.")
            expected = {creator_rules.normalize_username(name) for name in batch_creators}
            selected = chat_result["selected_usernames"]
            rate_limit = chat_result["rate_limit_usernames"]
            if (len(set(selected)) != len(selected) or len(set(rate_limit)) != len(rate_limit)
                    or set(selected) & set(rate_limit) or set(selected) | set(rate_limit) != expected
                    or chat_result.get("shared_count", chat_result.get("followup_count")) != len(selected)):
                raise RuntimeError("Kết quả chat không khớp danh sách đợt; chưa cập nhật Sheet.")
        except Exception as e:
            diagnostics.capture_error(bot.page, e)
            batch_state["error"] = str(e)
            progress.save()
            print(f"   ⚠️ Không chia sẻ được lời mời '{inv_name}' qua chat: {e}")
            raise
        from followup_chat import FollowupChat
        batch_state["stage"] = "followup"
        progress.save()
        chat_page = bot._open_saved_chat(chat_result["chat_url"])
        sender = FollowupChat(bot, chat_page)

        def save_followup():
            progress.save()
            count, day, limited = followup.summarize(recipients)
            sheet_mgr.update_followup_history(inv_name, count, limited, followup_day=day)
            print(f"   [FOLLOWUP] Đợt {batch_index}: {count}/{len(recipients)} đã gửi; giới hạn {len(limited)}.")

        # Đồng bộ lại Sheet trước khi tiếp tục nếu lần trước ghi Sheet bị lỗi.
        save_followup()
        try:
            for username, state in recipients.items():
                diagnostics.set_context(stage="followup", creator=username)
                sender.send_one(username, state, save_followup)
        except BaseException as error:
            batch_state["error"] = str(error)
            progress.save()
            diagnostics.capture_error(chat_page, error)
            raise
        if any(state["status"] not in ("sent", "rate_limited") for state in recipients.values()):
            raise RuntimeError("Còn người nhận chưa xử lý xong; giữ tab chat và checkpoint.")
        batch_state["stage"] = "update_followup_history"
        progress.save()
        save_followup()
        batch_state.update(status="completed", stage="done", error=None)
        progress.save()
        diagnostics.set_context(stage="done")
        chat_page.close()
        count, _, limited = followup.summarize(recipients)
        print(f"   ✓ Follow-up '{inv_name}': {count} tin riêng đã xác minh; rate limit: {len(limited)}.")

    def _resume_sent_chats(self, progress):
        batches = progress.blocking_batches
        # Do not resume any sends while another batch has an uncertain invitation result.
        for batch in batches:
            if batch['status'] != 'sent' or batch.get('stage') not in ('chat', 'followup', 'update_followup_history'):
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
