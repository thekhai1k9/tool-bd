"""Local, best-effort diagnostics. No browser actions or business state changes."""
import datetime
import json
import logging
import re
import sys
import uuid
from pathlib import Path


_active = None
_timezone = datetime.timezone(datetime.timedelta(hours=7))


class _Formatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return datetime.datetime.fromtimestamp(record.created, _timezone).isoformat(timespec="milliseconds")


class _FileHandler(logging.FileHandler):
    def handleError(self, record):
        # Do not recurse through mirrored stderr or interrupt an ongoing workflow.
        pass


class _ConsoleMirror:
    def __init__(self, stream, session, level):
        self.stream, self.session, self.level = stream, session, level
        self.pending = ""

    def write(self, text):
        result = self.stream.write(text)
        self.pending += text
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            if line.strip():
                self.session.record(self.level, line.rstrip("\r"))
        return result

    def flush(self):
        self.stream.flush()
        if self.pending:
            self.session.record(self.level, self.pending)
            self.pending = ""

    def __getattr__(self, name):
        return getattr(self.stream, name)


class RunSession:
    def __init__(self, output_dir="outputs"):
        self.output_dir = Path(output_dir)
        self.run_id = datetime.datetime.now(_timezone).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        self.context = dict(shop="-", sku="-", batch="-", stage="startup", keyword="-", creator="-")
        self.logger = logging.getLogger(f"at.run.{self.run_id}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.handler = None
        self.log_path = None
        self._warned = False
        self._failure_count = 0
        self.original_stdout, self.original_stderr = sys.stdout, sys.stderr
        try:
            logs = self.output_dir / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            log_path = logs / f"run_{self.run_id}.log"
            handler = _FileHandler(log_path, encoding="utf-8")
            handler.setFormatter(_Formatter(
                "%(asctime)s %(levelname)s run=%(run_id)s shop=%(shop)s sku=%(sku)s "
                "batch=%(batch)s stage=%(stage)s keyword=%(keyword)s creator=%(creator)s | %(message)s"
            ))
            self.logger.addHandler(handler)
            self.handler, self.log_path = handler, log_path
        except Exception as error:
            self.warn(error)

    def warn(self, error):
        if not self._warned:
            self._warned = True
            try:
                self.original_stderr.write(f"[diagnostics] Không lưu được một phần log/debug: {error}\n")
            except Exception:
                pass

    def record(self, level, message, error=None):
        if self.handler is None:
            return
        try:
            exc_info = (type(error), error, error.__traceback__) if error is not None else None
            self.logger.log(level, message, extra={"run_id": self.run_id, **self.context}, exc_info=exc_info)
        except Exception as failure:
            self.warn(failure)

    def __enter__(self):
        global _active
        self.previous, _active = _active, self
        self.stdout = _ConsoleMirror(self.original_stdout, self, logging.INFO)
        self.stderr = _ConsoleMirror(self.original_stderr, self, logging.ERROR)
        sys.stdout, sys.stderr = self.stdout, self.stderr
        self.record(logging.INFO, f"Run started; log={self.log_path}")
        return self

    def __exit__(self, exc_type, error, traceback):
        global _active
        if error is not None:
            self.record(logging.ERROR, "Run exited with exception", error)
        for mirror in (self.stdout, self.stderr):
            try:
                mirror.flush()
            except Exception as failure:
                self.warn(failure)
        if sys.stdout is self.stdout:
            sys.stdout = self.original_stdout
        if sys.stderr is self.stderr:
            sys.stderr = self.original_stderr
        _active = self.previous
        self.record(logging.INFO, "Run session ended")
        if self.handler is not None:
            try:
                self.logger.removeHandler(self.handler)
                self.handler.close()
            except Exception as failure:
                self.warn(failure)
        return False

    def capture(self, page, error):
        self.record(logging.ERROR, "Operation failed", error)
        if self.handler is None or page is None:
            return {}
        artifacts, failures = {}, {}
        try:
            if self.context["stage"] == "chat":
                pages = page.context.pages
                if isinstance(pages, (list, tuple)) and pages:
                    page = pages[-1]
            self._failure_count += 1
            stage = re.sub(r"[^a-zA-Z0-9_-]", "_", str(self.context["stage"]))[:60]
            folder = self.output_dir / "debug" / self.run_id
            folder.mkdir(parents=True, exist_ok=True)
            prefix = folder / f"{self._failure_count:03d}_{stage}"
            try:
                screenshot = prefix.with_suffix(".png")
                page.screenshot(path=str(screenshot), full_page=False, timeout=3000)
                artifacts["screenshot"] = str(screenshot)
            except Exception as failure:
                failures["screenshot"] = str(failure)
            try:
                selector = ".select-creators, [id^='core-select-popup-']:visible" if self.context["stage"] in (
                    "add_creators", "select_creators", "set_creator_page_size",
                ) else "body"
                regions = page.locator(selector)
                if regions.count() == 0:
                    regions = page.locator("body")
                fragments = [regions.nth(i).evaluate("element => element.outerHTML", timeout=2000)
                             for i in range(min(regions.count(), 6))]
                dom = prefix.with_suffix(".html")
                dom.write_text('<!doctype html><meta charset="utf-8">\n' + "\n".join(fragments), encoding="utf-8")
                artifacts["dom"] = str(dom)
            except Exception as failure:
                failures["dom"] = str(failure)
            metadata = prefix.with_suffix(".json")
            metadata.write_text(json.dumps({
                "run_id": self.run_id, "context": dict(self.context), "url": page.url,
                "error": str(error), "artifacts": dict(artifacts), "capture_errors": failures,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            artifacts["metadata"] = str(metadata)
            self.record(logging.INFO, f"Debug evidence: {artifacts}; capture_errors={failures}")
        except Exception as failure:
            self.warn(failure)
        return artifacts


def set_context(**fields):
    if _active is not None:
        for key, value in fields.items():
            if key in _active.context:
                _active.context[key] = "-" if value is None else value


def log_exception(message, error):
    if _active is not None:
        _active.record(logging.ERROR, message, error)


def event(message):
    if _active is not None:
        _active.record(logging.INFO, message)


def capture_error(page, error=None):
    if _active is not None:
        try:
            return _active.capture(page, error if error is not None else sys.exc_info()[1])
        except Exception as failure:
            _active.warn(failure)
    return {}
