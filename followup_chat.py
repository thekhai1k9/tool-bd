"""Gửi tuần tự trên tab chat; dừng nếu kết quả sau click chưa xác định."""
import re
from time import monotonic
import followup


class FollowupChat:
    def __init__(self, bot, page):
        self.bot, self.page = bot, page

    def open_recipient(self, username):
        page = self.page
        self.bot._check_captcha(page)
        search = page.get_by_placeholder("Tìm kiếm liên hệ...", exact=True)
        search.wait_for(state="visible", timeout=10000)
        search.fill(username)
        page.wait_for_timeout(1000)
        exact = re.compile(rf"^@?{re.escape(username)}$", re.IGNORECASE)
        items = page.locator('[role="listitem"].m4b-list-item').filter(has=page.get_by_text(exact))
        items.first.wait_for(state="visible", timeout=10000)
        if items.count() != 1:
            raise RuntimeError(f"Không có kết quả liên hệ duy nhất cho {username}")
        items.click()
        room = page.locator('[role="presentation"][class*="chatRoom-"]')
        if room.count() != 1:
            raise RuntimeError("Không xác định được duy nhất khung cuộc trò chuyện")
        identity = room.locator('[class*="chatRoomTopBar-"]').get_by_text(exact)
        identity.wait_for(state="visible", timeout=10000)
        if identity.count() != 1:
            raise RuntimeError(f"Chưa xác minh người nhận {username}")
        page.wait_for_timeout(1500)
        return room

    @staticmethod
    def message_snapshot(room, message):
        return room.locator('.chatd-message--right').evaluate_all("""(rows, content) => {
            const norm = s => s.replace(/\\r\\n/g, '\\n');
            return rows.filter(row => Array.from(row.querySelectorAll('.chatd-bubble--self pre'))
                .some(el => norm(el.textContent) === norm(content))).map(row => {
                const status = row.querySelector('.chatd-message-status');
                const signature = status ? [status.textContent, status.getAttribute('data-status'),
                    status.getAttribute('aria-label'), status.getAttribute('title'),
                    ...Array.from(status.querySelectorAll('*')).flatMap(el =>
                        [el.getAttribute('aria-label'), el.getAttribute('title'), el.getAttribute('data-status'),
                         el.getAttribute('class')])].filter(Boolean).join(' ') : '';
                return {status: signature, html: status ? status.outerHTML.slice(0, 1500) : ''};
            });
        }""", message)

    def send_one(self, username, state, save):
        if state["status"] in ("sending", "unknown"):
            raise RuntimeError(f"{username}: kết quả gửi trước chưa rõ; đối chiếu lịch sử, không tự gửi lại.")
        if state["status"] in ("sent", "rate_limited"):
            return
        page = self.page
        print(f"   [FOLLOWUP] Tìm và xác minh người nhận: {username}")
        self.bot._check_captcha(page)
        try:
            room = self.open_recipient(username)
        except Exception as error:
            # Theo quy ước vận hành: chưa bấm Gửi, không xác định được người/khả năng gửi = rate limit.
            state.update(status="rate_limited", reason=str(error), checked_at=followup.now())
            save()
            print(f"   [FOLLOWUP] {username}: chưa xác định được trước gửi, ghi giới hạn: {error}")
            return
        editor = room.locator('textarea#imTextarea[placeholder="Gửi tin nhắn"]')
        limit = room.get_by_text(re.compile(r"Bạn có thể gửi tối đa\s*5\s*tin nhắn"))
        limited = any(limit.nth(i).is_visible() for i in range(limit.count()))
        if limited or editor.count() != 1 or not editor.is_visible() or not editor.is_editable():
            state.update(status="rate_limited", reason="Giới hạn hoặc không có khung nhập khả dụng", checked_at=followup.now())
            save()
            print(f"   [FOLLOWUP] {username}: giới hạn, bỏ qua.")
            return
        message = state["message_snapshot"]
        editor.fill(message)
        if editor.input_value().replace("\r\n", "\n") != message.replace("\r\n", "\n"):
            raise RuntimeError("Nội dung khung nhập không khớp snapshot; chưa gửi")
        button = room.locator('#im_sdk_chat_input').get_by_role("button", name="Gửi", exact=True)
        if button.count() != 1 or not button.is_enabled():
            state.update(status="rate_limited", reason="Nút Gửi không khả dụng", checked_at=followup.now())
            save()
            return
        before = self.message_snapshot(room, message)
        state.update(status="sending", before_matching_count=len(before), started_at=followup.now())
        save()
        try:
            button.click(timeout=5000)
            print(f"   [FOLLOWUP] {username}: đã click Gửi, đang xác minh tin mới.")
            deadline = monotonic() + 30
            last = []
            while monotonic() < deadline:
                self.bot._check_captcha(page)
                last = self.message_snapshot(room, message)
                if len(last) > len(before):
                    status = last[-1]["status"]
                    # Không suy ra thành công từ bubble, ô nhập rỗng hoặc việc thiếu icon lỗi.
                    success = re.search(r"(?:^|[\s_-])(sent|delivered|success|succeeded)(?:$|[\s_-])|đã gửi|đã nhận", status, re.I)
                    failure = re.search(r"failed|error|pending|sending|loading|unsent|not[\s_-]*sent|cancel|retry|thất bại|đang gửi", status, re.I)
                    if success and not failure:
                        state.update(status="sent", sent_at=followup.now(), evidence=last[-1])
                        save()
                        print(f"   [FOLLOWUP] {username}: xác minh gửi thành công.")
                        page.wait_for_timeout(1500)
                        return
                page.wait_for_timeout(500)
            state["last_evidence"] = last[-1] if last else {}
            print(f"   [FOLLOWUP] {username}: chưa xác minh; DOM trạng thái={state['last_evidence']}")
            raise RuntimeError("Hết 30s chưa xác minh được trạng thái thành công của tin nhắn mới")
        except BaseException as error:
            if state["status"] == "sent":
                # Đã có bằng chứng thành công; lỗi ghi Sheet không làm mất trạng thái gửi.
                raise
            state.update(status="unknown", error=str(error), checked_at=followup.now())
            save()
            raise
