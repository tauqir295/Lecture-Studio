"""Tiny local audio player (Qt Multimedia) used for speaker samples and narration previews."""
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QUrl, Signal


class AudioPlayer(QObject):
    started = Signal(str)   # label of what is playing
    stopped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = None
        self._output = None
        self.current: Optional[str] = None
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            self._output = QAudioOutput(self)
            self._player = QMediaPlayer(self)
            self._player.setAudioOutput(self._output)
            self._player.playbackStateChanged.connect(self._on_state)
        except Exception:  # Qt Multimedia unavailable: playback silently disabled
            self._player = None

    @property
    def available(self) -> bool:
        return self._player is not None

    def play(self, path: Path, label: str = "") -> None:
        if not self._player:
            return
        self._player.stop()
        self.current = label or Path(path).name
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()
        self.started.emit(self.current)

    def stop(self) -> None:
        if self._player:
            self._player.stop()

    def is_playing(self) -> bool:
        if not self._player:
            return False
        from PySide6.QtMultimedia import QMediaPlayer
        return self._player.playbackState() == QMediaPlayer.PlayingState

    def _on_state(self, state) -> None:
        from PySide6.QtMultimedia import QMediaPlayer
        if state == QMediaPlayer.StoppedState:
            self.current = None
            self.stopped.emit()
