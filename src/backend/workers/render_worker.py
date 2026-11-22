"""Background Qt worker for re-rendering slides."""
from pathlib import Path
from typing import List, Optional
from PySide6.QtCore import QThread, Signal

from src.models.project import Project
from src.models.slide import Slide
from src.backend.slides.slide_renderer import SlideRenderer
from src.backend.project_manager import ProjectManager
from src.utils.logging_config import setup_logger

logger = setup_logger("render_worker")


class RenderWorker(QThread):
    """Worker thread for re-rendering slides without freezing the UI."""

    progress = Signal(int, str)
    slide_rendered = Signal(int, int)
    finished = Signal()
    error = Signal(str)

    def __init__(self, project: Project, slide_ids: Optional[List[str]] = None):
        super().__init__()
        self.project = project
        self.slide_ids = slide_ids  # None means re-render all
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        try:
            renderer = SlideRenderer(self.project.project_dir)
            source_file = Path(self.project.project_dir) / self.project.source_file

            slides_to_render = self.project.slides
            if self.slide_ids:
                slides_to_render = [s for s in self.project.slides if s.slide_id in self.slide_ids]

            total = len(slides_to_render)
            self.progress.emit(0, f"Starting render of {total} slides...")

            for i, slide in enumerate(slides_to_render):
                if self._is_cancelled:
                    self.error.emit("Rendering cancelled.")
                    return

                renderer.render_single_slide(source_file, slide)
                pct = int(((i + 1) / max(total, 1)) * 100)
                self.progress.emit(pct, f"Rendered slide {i + 1}/{total}")
                self.slide_rendered.emit(i + 1, total)

            pm = ProjectManager(Path(self.project.project_dir).parent)
            pm.save_project(self.project)
            self.progress.emit(100, "All slides rendered.")
            self.finished.emit()

        except Exception as exc:
            logger.exception("RenderWorker failed.")
            self.error.emit(str(exc))
