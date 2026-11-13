"""Tkinter front end. Run `python ui.py --demo` to preview without TikTok/Sheet."""
import argparse
import logging
import os
from pathlib import Path
import queue
import tkinter as tk
from tkinter import messagebox, ttk

from ui_runtime import DesktopSession
from config import resolve_spreadsheet_url


STAGES = {
    'load_sources': 'Đọc Google Sheet', 'browser_start': 'Mở trình duyệt',
    'login': 'Chờ đăng nhập', 'load_invitation_templates': 'Đọc mẫu lời mời',
    'sku_setup': 'Chuẩn bị SKU', 'checkpoint': 'Đọc checkpoint', 'filters': 'Lọc creator',
    'discover_creators': 'Tìm creator', 'target_navigation': 'Mở Cộng tác mục tiêu',
    'configure_invitation': 'Tạo lời mời', 'select_product': 'Chọn sản phẩm',
    'add_creators': 'Thêm creator', 'select_creators': 'Kiểm tra checkbox',
    'set_creator_page_size': 'Đặt 50/trang', 'awaiting_approval': 'Chờ duyệt gửi',
    'send': 'Đang gửi lời mời', 'verify_send': 'Chờ kết quả gửi',
    'log_history': 'Ghi lịch sử', 'chat': 'Chia sẻ qua chat', 'chat_resume': 'Khôi phục chat',
    'update_followup_history': 'Cập nhật follow-up', 'done': 'Hoàn tất đợt',
}


class AutomationWindow:
    def __init__(self, root, session=None, log_limit=10000, demo=False):
        self.root = root
        self.session = session if session is not None else DesktopSession()
        self.log_limit = log_limit
        self.pending_prompt = None
        self.closing = False
        self.status = tk.StringVar(value='Sẵn sàng')
        self.follow = tk.BooleanVar(value=True)
        self.response = tk.StringVar()
        self.sheet_url = tk.StringVar()
        self.context_vars = {key: tk.StringVar(value='—') for key in ('shop', 'sku', 'batch', 'stage')}
        root.title('TikTok Shop Automation' + (' — DEMO' if demo else ''))
        root.geometry('1120x790')
        root.minsize(880, 640)
        root.option_add('*Font', ('Segoe UI', 10))
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('Title.TLabel', font=('Segoe UI', 19, 'bold'))
        style.configure('Value.TLabel', font=('Segoe UI', 10, 'bold'))
        style.configure('Start.TButton', font=('Segoe UI', 10, 'bold'), padding=(16, 9))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frame = ttk.Frame(root, padding=18)
        frame.grid(sticky='nsew')
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)

        header = ttk.Frame(frame)
        header.grid(row=0, column=0, sticky='ew')
        ttk.Label(header, text='TikTok Shop Automation', style='Title.TLabel').pack(side='left')
        ttk.Label(header, textvariable=self.status, style='Value.TLabel').pack(side='right')
        subtitle = ('DEMO • Chỉ dữ liệu giả, không kết nối TikTok hoặc Google Sheet'
                    if demo else 'Trình duyệt Playwright mở riêng')
        ttk.Label(frame, text=subtitle).grid(row=1, column=0, sticky='w', pady=(4, 14))

        context = ttk.LabelFrame(frame, text='Phiên đang chạy', padding=10)
        context.grid(row=2, column=0, sticky='ew')
        for column, (key, title) in enumerate((('shop', 'SHOP'), ('sku', 'SKU ID'), ('batch', 'ĐỢT'), ('stage', 'BƯỚC HIỆN TẠI'))):
            cell = ttk.Frame(context, padding=(6, 0))
            cell.grid(row=0, column=column, sticky='ew')
            context.columnconfigure(column, weight=1 if key != 'batch' else 0)
            ttk.Label(cell, text=title, foreground='#64748b').pack(anchor='w')
            ttk.Label(cell, textvariable=self.context_vars[key], style='Value.TLabel').pack(anchor='w')

        sheet_row = ttk.Frame(context)
        sheet_row.grid(row=1, column=0, columnspan=4, sticky='ew', pady=(10, 0))
        sheet_row.columnconfigure(1, weight=1)
        ttk.Label(sheet_row, text='Link Google Sheet:').grid(row=0, column=0, padx=(6, 10))
        self.sheet_entry = ttk.Entry(sheet_row, textvariable=self.sheet_url)
        self.sheet_entry.grid(row=0, column=1, sticky='ew', padx=(0, 6))
        ttk.Label(context, text='Để trống: dùng link sheet mặc định. Link cần đúng format & dạng docs.google.com/spreadsheets/d/<ID>/edit; '
                  'Sheet phải đúng mẫu và có quyền truy cập.', wraplength=1000, foreground='#64748b').grid(
                      row=2, column=0, columnspan=4, sticky='w', padx=6, pady=(4, 0))

        controls = ttk.Frame(frame)
        controls.grid(row=3, column=0, sticky='ew', pady=12)
        self.start_button = ttk.Button(controls, text='Khởi chạy DEMO' if demo else 'Khởi chạy', style='Start.TButton', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(controls, text='Dừng an toàn', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=8)
        ttk.Button(controls, text='Mở thư mục log', command=self.open_log_directory).pack(side='right')

        log_frame = ttk.Frame(frame)
        log_frame.grid(row=4, column=0, sticky='nsew')
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(log_frame)
        toolbar.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 5))
        ttk.Label(toolbar, text='TOÀN BỘ LOG', style='Value.TLabel').pack(side='left')
        ttk.Checkbutton(toolbar, text='Tự cuộn', variable=self.follow, command=self.resume_follow).pack(side='left', padx=16)
        ttk.Button(toolbar, text='Xóa màn hình', command=self.clear_log).pack(side='right')
        ttk.Button(toolbar, text='Sao chép vùng chọn', command=self.copy_selection).pack(side='right', padx=8)
        self.log = tk.Text(log_frame, wrap='none', state='disabled', background='#111827',
                           foreground='#dbe4f0', insertbackground='white', selectbackground='#334e74',
                           font=('Consolas', 10), relief='flat', padx=12, pady=10)
        self.log.grid(row=1, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(log_frame, orient='vertical', command=self.scroll_log)
        vertical.grid(row=1, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(log_frame, orient='horizontal', command=self.log.xview)
        horizontal.grid(row=2, column=0, sticky='ew')
        self.log.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.log.tag_configure('error', foreground='#fca5a5')
        self.log.tag_configure('warning', foreground='#fcd34d')
        self.log.tag_configure('success', foreground='#86efac')
        self.log.tag_configure('info', foreground='#dbe4f0')
        self.log.bind('<MouseWheel>', lambda event: self.follow.set(False))
        self.log.bind('<Prior>', lambda event: self.follow.set(False))
        self.log.bind('<Up>', lambda event: self.follow.set(False))

        self.prompt_box = ttk.LabelFrame(frame, text='Tương tác / xác nhận', padding=10)
        self.prompt_box.grid(row=5, column=0, sticky='ew', pady=(12, 0))
        self.prompt_label = ttk.Label(self.prompt_box, text='Các câu hỏi đăng nhập, gửi lời mời và chat sẽ xuất hiện ở đây.',
                                      wraplength=1000, justify='left')
        self.prompt_label.pack(anchor='w')
        self.answers = ttk.Frame(self.prompt_box)
        self.answers.pack(fill='x', pady=(8, 0))
        ttk.Label(frame, text=f'Hiển thị tối đa {log_limit:,} dòng gần nhất; file log giữ toàn bộ nội dung.',
                  foreground='#64748b').grid(row=6, column=0, sticky='w', pady=(8, 0))
        root.bind('<Return>', self._enter_response)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.append_output('Sẵn sàng. ' + subtitle + '\n', logging.INFO)
        self.root.after(100, self.poll_events)

    def start(self):
        try:
            url = resolve_spreadsheet_url(self.sheet_url.get())
        except ValueError as error:
            messagebox.showwarning('Link Google Sheet không hợp lệ',
                                   f'{error}\nĐể trống nếu muốn dùng link trong config.py. Chưa khởi chạy automation.',
                                   parent=self.root)
            self.sheet_entry.focus_set()
            return
        if not self.session.start(spreadsheet_url=url):
            return
        self.sheet_entry.configure(state='disabled')
        self.status.set('Đang chạy')
        self.start_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.append_output('\n──────── BẮT ĐẦU LƯỢT CHẠY ────────\n', logging.INFO)

    def stop(self):
        self.session.request_stop()
        self.status.set('Đang dừng — chờ thao tác hiện tại')
        self.stop_button.configure(state='disabled')
        self.clear_prompt()

    def close(self):
        if self.closing:
            return
        if self.session.active:
            text = ('Yêu cầu dừng tại điểm an toàn, giữ checkpoint rồi đóng ứng dụng và trình duyệt?\n'
                    'Nếu đang gửi, ứng dụng sẽ chờ thao tác hiện tại kết thúc; không đóng ngang.')
        else:
            text = 'Đóng ứng dụng và phiên trình duyệt của ứng dụng? Cookie và checkpoint được giữ lại.'
        if not messagebox.askyesno('Đóng ứng dụng', text, parent=self.root):
            return
        self.closing = True
        self.status.set('Đang dừng và đóng phiên…')
        self.start_button.configure(state='disabled')
        self.stop_button.configure(state='disabled')
        self.sheet_entry.configure(state='disabled')
        self.clear_prompt()
        self.session.close()

    def show_prompt(self, prompt):
        self.clear_prompt()
        self.pending_prompt = prompt
        self.prompt_label.configure(text=prompt.message)
        if not self.closing and not self.session.stop_event.is_set():
            self.status.set('Chờ bạn xác nhận')
        if prompt.kind == 'confirm':
            label = 'Chia sẻ qua chat' if 'qua chat' in prompt.message.lower() else 'Gửi lời mời'
            ttk.Button(self.answers, text=label, command=lambda: self.respond('y')).pack(side='left')
            ttk.Button(self.answers, text='Chưa gửi', command=lambda: self.respond('n')).pack(side='left', padx=8)
        elif prompt.kind == 'continue':
            ttk.Button(self.answers, text='Đã đăng nhập — Tiếp tục', command=lambda: self.respond('')).pack(side='left')
        else:
            entry = ttk.Entry(self.answers, textvariable=self.response)
            entry.pack(side='left', fill='x', expand=True)
            ttk.Button(self.answers, text='Gửi phản hồi', command=self.submit_response).pack(side='left', padx=8)
            ttk.Button(self.answers, text='Giữ lại / Không tiếp tục', command=lambda: self.respond('')).pack(side='left')
            entry.focus_set()

    def clear_prompt(self):
        self.pending_prompt = None
        self.response.set('')
        for widget in self.answers.winfo_children():
            widget.destroy()
        self.prompt_label.configure(text='Không có yêu cầu xác nhận đang chờ.')

    def respond(self, value):
        prompt = self.pending_prompt
        if prompt is None or self.closing or self.session.stop_event.is_set():
            return
        self.clear_prompt()
        prompt.reply(value)
        self.status.set('Đang chạy')

    def submit_response(self):
        self.respond(self.response.get())

    def _enter_response(self, event):
        if self.pending_prompt is not None and self.pending_prompt.kind not in ('confirm', 'continue'):
            self.submit_response()
            return 'break'

    def append_output(self, text, level):
        self.log.configure(state='normal')
        for line in text.splitlines(keepends=True):
            if level >= logging.ERROR or any(word in line for word in ('❌', 'Traceback', 'Đã xảy ra lỗi')):
                tag = 'error'
            elif '⚠' in line:
                tag = 'warning'
            elif '✓' in line or '✔' in line:
                tag = 'success'
            else:
                tag = 'info'
            self.log.insert('end', line, tag)
        lines = int(self.log.index('end-1c').split('.')[0])
        if lines > self.log_limit:
            self.log.delete('1.0', f'{lines - self.log_limit + 1}.0')
        self.log.configure(state='disabled')
        if self.follow.get():
            self.log.see('end')

    def poll_events(self, schedule=True):
        # Bound work per tick so log bursts cannot starve Tk input/paint events.
        output, output_level = [], logging.INFO

        def flush():
            if output:
                self.append_output(''.join(output), output_level)
                output.clear()

        for _ in range(1500):
            try:
                kind, value = self.session.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'output':
                text, level = value
                if level != output_level:
                    flush()
                    output_level = level
                output.append(text)
                continue
            flush()
            if kind == 'context':
                for key, variable in self.context_vars.items():
                    field = value.get(key, '—')
                    variable.set(STAGES.get(field, str(field)) if key == 'stage' else str(field))
            elif kind == 'prompt':
                if not self.closing and not self.session.stop_event.is_set():
                    self.show_prompt(value)
            elif kind == 'prompt_done':
                if self.pending_prompt is value:
                    self.clear_prompt()
            elif kind == 'done':
                self.clear_prompt()
                if not self.closing:
                    self.status.set({'completed': 'Hoàn tất', 'stopped': 'Đã dừng an toàn',
                                     'failed': 'Có bước chưa hoàn tất — xem log'}.get(value, value))
                    self.start_button.configure(state='normal')
                    self.stop_button.configure(state='disabled')
                    self.sheet_entry.configure(state='normal')
            elif kind == 'closed':
                flush()
                if self.closing:
                    self.root.destroy()
                    return
                self.status.set('Phiên đã đóng — mở lại ứng dụng để chạy')
                self.start_button.configure(state='disabled')
                self.stop_button.configure(state='disabled')
                self.sheet_entry.configure(state='disabled')
        flush()
        if schedule:
            self.root.after(100, self.poll_events)

    def scroll_log(self, *args):
        self.follow.set(False)
        self.log.yview(*args)

    def resume_follow(self):
        if self.follow.get():
            self.log.see('end')

    def clear_log(self):
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.configure(state='disabled')

    def copy_selection(self):
        try:
            selected = self.log.get('sel.first', 'sel.last')
        except tk.TclError:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(selected)

    def open_log_directory(self):
        folder = self.session.output_dir / 'logs'
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            messagebox.showerror('Không mở được thư mục log', str(error), parent=self.root)
            return
        self._open_path(folder)

    def _open_path(self, path):
        try:
            os.startfile(str(path.resolve()))
        except OSError as error:
            messagebox.showerror('Không mở được file/thư mục', str(error), parent=self.root)
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true', help='Chỉ chạy giao diện với dữ liệu giả')
    args = parser.parse_args(argv)
    os.chdir(Path(__file__).resolve().parent)
    run = None
    if args.demo:
        try:
            from test.demo.ui_demo import demo_run
        except ModuleNotFoundError:
            parser.error('DEMO chỉ có trên máy có thư mục test/demo; chạy python ui.py để dùng giao diện thật.')
        run = demo_run
    root = tk.Tk()
    session = DesktopSession(run=run)
    AutomationWindow(root, session=session, demo=args.demo)
    root.mainloop()


if __name__ == '__main__':
    main()
