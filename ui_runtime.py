"""Queue-based desktop adapter. Playwright is created, reused and closed on one worker."""
from dataclasses import dataclass, field
import logging
from pathlib import Path
import queue
import threading
import traceback

import diagnostics
import interaction
from config import resolve_spreadsheet_url


@dataclass
class Prompt:
    message: str
    kind: str
    answered: threading.Event = field(default_factory=threading.Event)
    value: str = ''

    def reply(self, value):
        if not self.answered.is_set():
            self.value = value
            self.answered.set()


class DesktopSession:
    def __init__(self, run=None, output_dir='outputs'):
        self.run = run
        self.output_dir = Path(output_dir)
        self.events = queue.Queue()
        self.commands = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = None
        self.bot = None
        self.active = False
        self.closing = False
        self.closed = False
        self.lock = threading.Lock()

    def start(self, spreadsheet_url=None):
        with self.lock:
            if self.active or self.closing:
                return False
            url = resolve_spreadsheet_url(spreadsheet_url)
            self.active = True
            self.stop_event.clear()
            if self.thread is None:
                self.thread = threading.Thread(target=self._worker, name='TikTok automation', daemon=False)
                self.thread.start()
            self.commands.put(('run', url))
        return True

    def request_stop(self):
        self.stop_event.set()

    def close(self):
        with self.lock:
            if self.closed:
                self.events.put(('closed', None))
                return
            if self.closing:
                return
            self.closing = True
            self.stop_event.set()
            if self.thread is None:
                self.closed = True
                self.events.put(('closed', None))
            else:
                self.commands.put('close')

    def check_stop(self):
        if self.stop_event.is_set():
            raise interaction.StopRequested()

    def ask(self, message, kind):
        self.check_stop()
        print(message, flush=True)
        prompt = Prompt(message, kind)
        self.events.put(('prompt', prompt))
        try:
            while not prompt.answered.wait(.1):
                self.check_stop()
            self.check_stop()
            print(f'[Trả lời] {prompt.value}', flush=True)
            return prompt.value
        finally:
            self.events.put(('prompt_done', prompt))

    def _output(self, text, level):
        self.events.put(('output', (text, level)))

    def _run_workflow(self, spreadsheet_url):
        # Lazy imports let the UI display dependency/import failures instead of disappearing.
        from app import main
        from browser_helper import TikTokBrowserAutomation
        if self.bot is not None:
            unusable = (self.bot.page is not None and self.bot.page.is_closed())
            partial_start = self.bot.page is None and self.bot.playwright is not None
            if unusable:
                try:
                    # Keep other chat/draft tabs when only the original search tab was closed.
                    self.bot.page = self.bot.browser_context.new_page()
                except Exception:
                    try:
                        self.bot.close()
                    finally:
                        self.bot = None
            elif partial_start:
                try:
                    self.bot.close()
                finally:
                    self.bot = None
        if self.bot is None:
            self.bot = TikTokBrowserAutomation()
        return main(bot=self.bot, spreadsheet_url=spreadsheet_url)

    def _worker(self):
        try:
            while True:
                command = self.commands.get()
                if command == 'close':
                    break
                _, spreadsheet_url = command
                status = 'completed'
                with interaction.use_interface(self):
                    with diagnostics.RunSession(
                        self.output_dir, on_output=self._output,
                        on_context=lambda context: self.events.put(('context', context)),
                    ) as session:
                        self.events.put(('log_path', session.log_path))
                        try:
                            self.check_stop()
                            outcome = self.run() if self.run is not None else self._run_workflow(spreadsheet_url)
                            if outcome is False:
                                status = 'failed'
                        except interaction.StopRequested:
                            status = 'stopped'
                            print('⏸ Đã dừng tại điểm an toàn. Giữ checkpoint và trình duyệt để kiểm tra.')
                        except Exception:
                            status = 'failed'
                            traceback.print_exc()
                with self.lock:
                    self.active = False
                self.events.put(('done', status))
        except BaseException:
            self._output(traceback.format_exc(), logging.ERROR)
            with self.lock:
                self.active = False
                self.closing = True
        finally:
            if self.bot is not None:
                try:
                    self.bot.close()
                except Exception:
                    self._output(traceback.format_exc(), logging.ERROR)
            with self.lock:
                self.closed = True
            self.events.put(('closed', None))
