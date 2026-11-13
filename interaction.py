"""Prompts and cooperative stop points shared by CLI and desktop UI."""
from contextlib import contextmanager
import threading


_local = threading.local()


class StopRequested(BaseException):
    """Bypass broad business exception handlers; stop only at explicit checkpoints."""


@contextmanager
def use_interface(interface):
    previous = getattr(_local, 'interface', None)
    _local.interface = interface
    try:
        yield
    finally:
        _local.interface = previous


def checkpoint():
    interface = getattr(_local, 'interface', None)
    if interface is not None:
        interface.check_stop()


def ask(message, kind='text'):
    interface = getattr(_local, 'interface', None)
    if interface is None:
        return input(message)
    return interface.ask(message, kind)
