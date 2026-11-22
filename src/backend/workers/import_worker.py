"""Background Qt worker for asynchronous presentation import and slide processing."""
import json
from pathlib import Path
from typing import Optional
from PySide6.QtCore import QThread, Signal

from src.models.project import Project, WorkflowStage
from src.models.video_config import VideoConfig
from src.backend.project_manager import ProjectManager
from src.backend.slides.pdf_parser import PDFPresentationParser
from src.backend.slides.slide_renderer import SlideRenderer
from src.backend.narration.narration_manager import NarrationManager
from src.backend.companion import CompanionPackage, find_companion, apply_companion
from src.backend.content.profiles import GENERIC, detect_profile, load_profiles
from src.utils.logging_config import setup_logger

logger = setup_logger("import_worker")


class ImportWorker(QThread):
    """Worker thread that imports a PDF presentation without freezing the GUI."""

    progress = Signal(int, str)  # percent, status message
    slide_processed = Signal(int, int)  # current, total
    finished = Signal(object)  # Project instance
    error = Signal(str)

    def __init__(
        self,
        source_path: str | Path,
        project_name: str,
        workspace_dir: Optional[str | Path] = None,
        custom_dir: Optional[str | Path] = None,
        settings: Optional[VideoConfig] = None,
        profile_id: str = "auto",
    ):
        super().__init__()
        self.source_path = Path(source_path).resolve()
        self.project_name = project_name
        self.workspace_dir = workspace_dir
        self.custom_dir = custom_dir
        self.settings = settings or VideoConfig()
        self.profile_id = profile_id or "auto"
        self._is_cancelled = False
        self.warnings: list = []

    def cancel(self) -> None:
        """Request safe cancellation of the import process."""
        self._is_cancelled = True
        logger.info("Cancellation requested for import worker.")

    def run(self) -> None:
        try:
            self.progress.emit(5, "Creating project directories...")
            pm = ProjectManager(self.workspace_dir)

            project = pm.create_project(
                name=self.project_name,
                source_path=self.source_path,
                custom_dir=self.custom_dir,
                settings=self.settings,
            )

            if self._is_cancelled:
                self.error.emit("Import cancelled by user.")
                return

            generated = None
            if project.source_type != "pdf":
                from src.backend.content.pipeline import convert_source
                self.progress.emit(10, f"Converting {self.source_path.name} ({project.source_type}) into video slides...")
                # convert from the original location so relative images resolve
                result = convert_source(self.source_path, Path(project.project_dir) / "source")
                project.original_source = project.source_file
                project.source_file = f"source/{result.pdf.name}"
                self.warnings += result.warnings
                data = json.loads(result.manifest.read_text(encoding="utf-8"))
                generated = CompanionPackage(result.manifest, data, data.get("slides", []), {})

            self.progress.emit(15, f"Parsing presentation structure from {self.source_path.name}...")
            # Use source copied into project
            copied_source = Path(project.project_dir) / project.source_file
            parser = PDFPresentationParser(copied_source)
            slides, summary = parser.parse_slides()

            if not slides:
                raise ValueError("No slides could be extracted from the presentation.")

            project.slides = slides
            project.slide_count = len(slides)

            if self._is_cancelled:
                self.error.emit("Import cancelled by user.")
                return

            self.progress.emit(35, f"Rendering {len(slides)} slides at 1920x1080 and generating thumbnails...")
            renderer = SlideRenderer(project.project_dir)

            def on_render_progress(current: int, total: int, msg: str):
                if self._is_cancelled:
                    return
                # Map rendering from 35% to 85%
                pct = 35 + int((current / max(total, 1)) * 50)
                self.progress.emit(pct, f"Rendering slide {current} of {total}...")
                self.slide_processed.emit(current, total)

            renderer.render_all_slides(
                pdf_path=copied_source,
                slides=project.slides,
                progress_callback=on_render_progress,
                cancel_check=lambda: self._is_cancelled,
            )

            if self._is_cancelled:
                self.error.emit("Import cancelled by user.")
                return

            companion = generated or find_companion(self.source_path)
            if companion:
                self.progress.emit(88, f"Loading companion lecture package ({companion.summary()})...")
                for w in apply_companion(project, companion):
                    logger.warning(w)
            else:
                self.progress.emit(88, "Drafting initial narration scripts for slides...")
            # Drafts narration only for slides the companion package did not cover.
            nm = NarrationManager(project)
            nm.generate_initial_narrations()

            self._apply_profile(project)

            self.progress.emit(95, "Persisting project state...")
            project.workflow_stage = WorkflowStage.SLIDE_REVIEW
            pm.save_project(project)

            self.progress.emit(100, f"Successfully imported {len(slides)} slides.")
            logger.info(f"ImportWorker completed successfully for '{project.project_name}'")
            self.finished.emit(project)

        except Exception as exc:
            logger.exception("Import worker failed.")
            self.error.emit(str(exc))

    def _apply_profile(self, project) -> None:
        """Optional topic profile: seeds TTS pronunciations. 'generic' adds nothing."""
        ws = Path(self.workspace_dir) if self.workspace_dir else Path.cwd()
        profiles = load_profiles([ws / "profiles"])
        pid = self.profile_id
        if pid == "auto":
            text = "\n".join([s.title + "\n" + s.original_text for s in project.slides] +
                             [n.script for n in project.narrations])
            pid = detect_profile(text, profiles)
        prof = profiles.get(pid) or profiles[GENERIC]
        project.content_profile = prof.id
        project.settings.pronunciations = {**prof.pronunciations, **project.settings.pronunciations}
        logger.info(f"Content profile: {prof.id}")
