import logging
from typing import Callable

from PySide6.QtCore import QThread, Signal

log = logging.getLogger(__name__)


class Worker(QThread):
    """Run a callable off the UI thread. Emits ``failed(str)`` on exception, ``finished`` always.

    Cancel is Qt's own ``requestInterruption()``; the callable polls ``isInterruptionRequested``.
    """

    failed = Signal(str)
    message = Signal(str)  # thread-safe log channel for the callable
    progress = Signal(int, int)  # done, total

    def __init__(self, fn: Callable[[], None], parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self._fn()
        except Exception as exc:  # noqa: BLE001 - surface anything to the log
            log.exception("feature failed")  # full traceback to the log file, short message to the UI
            self.failed.emit(str(exc) or type(exc).__name__)
