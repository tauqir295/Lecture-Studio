"""Generic background worker for TTS tasks (model load/download, samples, previews, generation)."""
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

from src.utils.logging_config import setup_logger

logger = setup_logger("tts_worker")


class TTSTaskWorker(QThread):
    """Runs fn(progress, cancel) off the GUI thread. `kind` tags the task for the UI."""

    progress = Signal(int, str)
    finished_ok = Signal(str, object)   # kind, result
    failed = Signal(str, str)           # kind, message

    def __init__(self, kind: str, fn: Callable[[Callable[[int, str], None], Callable[[], bool]], Any]):
        super().__init__()
        self.kind = kind
        self._fn = fn
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            result = self._fn(lambda p, m: self.progress.emit(p, m), lambda: self._cancel)
            self.finished_ok.emit(self.kind, result)
        except Exception as exc:
            logger.exception(f"TTS task '{self.kind}' failed")
            self.failed.emit(self.kind, str(exc))
