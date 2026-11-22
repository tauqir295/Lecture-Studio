"""Slide renderer for generating high-resolution slide images and thumbnails."""
import sys
from pathlib import Path
from typing import Callable, Optional, List
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PySide6.QtPdf import QPdfDocument
from PySide6.QtCore import QSize

from src.models.slide import Slide
from src.utils.paths import ProjectPaths
from src.utils.logging_config import setup_logger

logger = setup_logger("slide_renderer")


class SlideRenderer:
    """Renders PDF slides to 1920x1080 PNG images and high-fidelity thumbnails."""

    def __init__(self, project_dir: str | Path):
        self.paths = ProjectPaths(project_dir)
        self.paths.ensure_directories()
        self._ensure_qt_app()

    @staticmethod
    def _ensure_qt_app() -> QApplication:
        """Ensure a QApplication exists for rendering."""
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv if sys.argv else ["PPTLectureStudio"])
        return app

    def render_all_slides(
        self,
        pdf_path: str | Path,
        slides: List[Slide],
        target_width: int = 1920,
        target_height: int = 1080,
        thumb_width: int = 320,
        thumb_height: int = 180,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[Slide]:
        """Render full-resolution images and thumbnails for all slides in the PDF."""
        pdf_file = Path(pdf_path).resolve()
        if not pdf_file.is_file():
            raise FileNotFoundError(f"PDF file does not exist: {pdf_file}")

        doc = QPdfDocument()
        status = doc.load(str(pdf_file))
        page_count = doc.pageCount()

        if page_count == 0:
            raise ValueError(f"Failed to load PDF or PDF has 0 pages: {pdf_file}")

        total = len(slides)
        for i, slide in enumerate(slides):
            if cancel_check and cancel_check():
                logger.info("Slide rendering cancelled by user.")
                break

            page_idx = slide.slide_number - 1
            if page_idx >= page_count:
                logger.warning(f"Slide index {page_idx} exceeds PDF page count {page_count}")
                continue

            # Calculate proper aspect ratio size
            point_size = doc.pagePointSize(page_idx)
            aspect = point_size.width() / max(point_size.height(), 1.0)

            # Determine slide image dimensions preserving aspect ratio
            img_w = target_width
            img_h = int(target_width / aspect)
            if img_h > target_height:
                img_h = target_height
                img_w = int(target_height * aspect)

            # Render full-size image
            img = doc.render(page_idx, QSize(img_w, img_h))
            img_filename = f"{slide.slide_id}.png"
            full_img_path = self.paths.slides / img_filename
            img.save(str(full_img_path), "PNG")

            # Render thumbnail
            t_w = thumb_width
            t_h = int(thumb_width / aspect)
            thumb = doc.render(page_idx, QSize(t_w, t_h))
            thumb_filename = f"{slide.slide_id}_thumb.png"
            thumb_path = self.paths.preview / thumb_filename
            thumb.save(str(thumb_path), "PNG")

            # Update slide relative paths
            slide.image_path = f"slides/{img_filename}"
            slide.thumbnail_path = f"preview/{thumb_filename}"

            if progress_callback:
                progress_callback(i + 1, total, f"Rendered slide {i + 1}/{total}")

        logger.info(f"Rendered {total} slide images and thumbnails.")
        doc.close()
        return slides

    def render_single_slide(
        self,
        pdf_path: str | Path,
        slide: Slide,
        target_width: int = 1920,
        thumb_width: int = 320,
    ) -> Slide:
        """Render or re-render a single slide."""
        doc = QPdfDocument()
        doc.load(str(Path(pdf_path).resolve()))
        page_idx = slide.slide_number - 1

        point_size = doc.pagePointSize(page_idx)
        aspect = point_size.width() / max(point_size.height(), 1.0)

        img_w = target_width
        img_h = int(target_width / aspect)
        img = doc.render(page_idx, QSize(img_w, img_h))

        img_filename = f"{slide.slide_id}.png"
        full_img_path = self.paths.slides / img_filename
        img.save(str(full_img_path), "PNG")

        thumb = doc.render(page_idx, QSize(thumb_width, int(thumb_width / aspect)))
        thumb_filename = f"{slide.slide_id}_thumb.png"
        thumb_path = self.paths.preview / thumb_filename
        thumb.save(str(thumb_path), "PNG")

        slide.image_path = f"slides/{img_filename}"
        slide.thumbnail_path = f"preview/{thumb_filename}"

        doc.close()
        return slide
