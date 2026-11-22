"""Background Qt worker that runs the video generation pipeline."""
from PySide6.QtCore import QThread, Signal

from src.backend.video.pipeline import Cancelled, generate_video
from src.backend.video.timing import RenderSettings
from src.models.project import Project
from src.utils.logging_config import setup_logger

logger = setup_logger("video_worker")


class VideoRenderWorker(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(dict)   # render report
    failed = Signal(str)

    def __init__(self, project: Project, settings: RenderSettings):
        super().__init__()
        self.project = project
        self.settings = settings
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            report = generate_video(self.project, self.settings,
                                    progress=lambda p, m: self.progress.emit(p, m),
                                    cancel_check=lambda: self._cancel)
            self.finished_ok.emit(report)
        except Cancelled as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # surface any pipeline error to the UI
            logger.exception("Video generation failed.")
            self.failed.emit(str(exc))


class TransitionPreviewWorker(QThread):
    """Renders a short low-resolution transition preview (frames) off the UI thread."""
    ready = Signal(object, int, int, float)   # frames (List[bytes]), width, height, fps
    failed = Signal(str)

    def __init__(self, project: Project, from_id: str, to_id: str, key: str, seconds: float, width: int = 480):
        super().__init__()
        self.args = (project, from_id, to_id, key, seconds, width)

    def run(self) -> None:
        from src.backend.video.pipeline import transition_preview_frames
        try:
            frames, w, h, fps = transition_preview_frames(*self.args)
            self.ready.emit(frames, w, h, fps)
        except Exception as exc:
            logger.exception("Transition preview failed.")
            self.failed.emit(str(exc))
