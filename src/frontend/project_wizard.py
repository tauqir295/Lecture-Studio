"""New Project Wizard dialog."""
from pathlib import Path
from typing import Optional, List
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QGroupBox, QMessageBox
)
from PySide6.QtCore import Qt, Signal

from src.models.project import Project
from src.models.video_config import VideoConfig
from src.backend.workers.import_worker import ImportWorker
from src.backend.companion import find_companion
from src.backend.content.importers import SUPPORTED_EXT, detect_type
from src.backend.content.profiles import load_profiles
from src.frontend.progress_dialog import ProgressDialog


class ProjectWizard(QDialog):
    """Wizard dialog for creating and importing a new presentation project."""

    project_created = Signal(object)  # Emits Project instance

    def __init__(self, workspace_root: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self.workspace_root = workspace_root or Path.cwd()
        self.setWindowTitle("Create New Project — PPT Lecture Studio")
        self.resize(560, 480)
        self.worker: Optional[ImportWorker] = None
        self.progress_dialog: Optional[ProgressDialog] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QLabel("New Presentation Project")
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #93c5fd;")
        layout.addWidget(header)

        desc = QLabel("Import a PDF, PowerPoint, Word, Markdown, text or code file on any topic. "
                      "Non-PDF sources are turned into 16:9 video slides with drafted narration.")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #9ca3af;")
        layout.addWidget(desc)

        # Project Details Group
        details_group = QGroupBox("Project Information")
        dg_layout = QVBoxLayout(details_group)
        dg_layout.setSpacing(10)

        dg_layout.addWidget(QLabel("Project Name:"))
        self.name_edit = QLineEdit("")
        self.name_edit.setPlaceholderText("e.g. Introduction to Machine Learning")
        dg_layout.addWidget(self.name_edit)

        # Source Presentation
        dg_layout.addWidget(QLabel("Source File (PDF, PPTX, DOCX, Markdown, text or code):"))
        file_row = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("Select presentation file...")
        file_row.addWidget(self.file_edit, 1)

        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.clicked.connect(self._on_browse_file)
        file_row.addWidget(self.btn_browse)
        dg_layout.addLayout(file_row)

        # Quick Preset Samples
        sample_row = QHBoxLayout()
        sample_row.addWidget(QLabel("Or choose a sample:"))
        self.sample_combo = QComboBox()
        self.sample_combo.addItem("Select sample presentation...", "")
        self._populate_samples()
        self.sample_combo.currentIndexChanged.connect(self._on_sample_selected)
        sample_row.addWidget(self.sample_combo, 1)
        dg_layout.addLayout(sample_row)

        prof_row = QHBoxLayout()
        prof_row.addWidget(QLabel("Topic profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.addItem("Auto-detect from content", "auto")
        for prof in sorted(load_profiles([self.workspace_root / "profiles"]).values(), key=lambda x: x.name):
            self.profile_combo.addItem(prof.name, prof.id)
            self.profile_combo.setItemData(self.profile_combo.count() - 1, prof.description, Qt.ToolTipRole)
        self.profile_combo.setToolTip("Optional topic knowledge (e.g. pronunciations). "
                                      "'General' works for any subject.")
        prof_row.addWidget(self.profile_combo, 1)
        dg_layout.addLayout(prof_row)

        self.companion_label = QLabel("")
        self.companion_label.setWordWrap(True)
        self.companion_label.setStyleSheet("color: #86efac;")
        dg_layout.addWidget(self.companion_label)
        self.file_edit.textChanged.connect(self._update_companion_info)

        layout.addWidget(details_group)

        # Video Settings
        settings_group = QGroupBox("Video Settings")
        sg_layout = QVBoxLayout(settings_group)

        res_row = QHBoxLayout()
        res_row.addWidget(QLabel("Target Resolution:"))
        self.res_combo = QComboBox()
        self.res_combo.addItems([
            "1920x1080 (1080p Full HD, 16:9)",
            "1280x720 (720p HD, 16:9)",
        ])
        res_row.addWidget(self.res_combo, 1)
        sg_layout.addLayout(res_row)

        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel("Frame Rate:"))
        self.fps_combo = QComboBox()
        self.fps_combo.addItems(["30 FPS (Standard)", "60 FPS (Smooth)"])
        fps_row.addWidget(self.fps_combo, 1)
        sg_layout.addLayout(fps_row)

        layout.addWidget(settings_group)
        layout.addStretch()

        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_create = QPushButton("Create & Import Project")
        self.btn_create.setObjectName("primaryBtn")
        self.btn_create.clicked.connect(self._on_create_project)
        btn_layout.addWidget(self.btn_create)

        layout.addLayout(btn_layout)

    def _populate_samples(self) -> None:
        for samples_dir in (self.workspace_root / "docs" / "pdfs", self.workspace_root / "docs" / "samples"):
            if samples_dir.is_dir():
                for p in sorted(samples_dir.iterdir()):
                    if p.is_file() and p.suffix.lower() in SUPPORTED_EXT:
                        self.sample_combo.addItem(f"📄 {p.name}", str(p))
        # Rebuilt video lectures that ship with a companion package (narration etc.)
        for p in sorted((self.workspace_root / "output").glob("*/*.pdf")):
            if find_companion(p):
                self.sample_combo.addItem(f"🎬 {p.stem.replace('_', ' ')} (with narration)", str(p))

    def _update_companion_info(self, path: str) -> None:
        pkg = None
        if path and Path(path).is_file():
            try:
                kind = detect_type(Path(path))
            except ValueError as exc:
                self.companion_label.setText(f"✗ {exc}")
                return
            if kind != "pdf":
                self.companion_label.setText(f"Source type: {kind}. It will be converted into 16:9 video slides "
                                             "with drafted narration (all source text is kept).")
                return
            pkg = find_companion(path)
        if pkg:
            roles = ", ".join(sorted(pkg.files)) or "none"
            self.companion_label.setText(
                f"✔ Companion lecture package found: {pkg.summary()}.\n"
                f"Narration scripts will be loaded and these files added to the project: {roles}.")
        else:
            self.companion_label.setText("")

    def _on_sample_selected(self, index: int) -> None:
        file_path = self.sample_combo.currentData()
        if file_path:
            self.file_edit.setText(file_path)
            self.name_edit.setText(Path(file_path).stem.replace("_", " "))

    def _on_browse_file(self) -> None:
        start_dir = str(self.workspace_root / "docs" / "pdfs")
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Presentation File",
            start_dir,
            "Supported sources (" + " ".join("*" + e for e in sorted(SUPPORTED_EXT)) + ");;"
            "PDF (*.pdf);;PowerPoint (*.pptx);;Word (*.docx);;Markdown (*.md *.markdown);;Text (*.txt);;All files (*)",
        )
        if path:
            self.file_edit.setText(path)
            stem = Path(path).stem.replace("_", " ")
            self.name_edit.setText(stem)

    def _on_create_project(self) -> None:
        name = self.name_edit.text().strip()
        source_path = self.file_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "Validation Error", "Please provide a project name.")
            return

        if not source_path or not Path(source_path).is_file():
            QMessageBox.warning(self, "Validation Error", "Please choose a valid presentation file.")
            return

        # Video config
        config = VideoConfig()
        if "1280x720" in self.res_combo.currentText():
            config.resolution = "1280x720"
            config.width = 1280
            config.height = 720
        if "60 FPS" in self.fps_combo.currentText():
            config.fps = 60

        # Start background worker
        self.progress_dialog = ProgressDialog("Importing Presentation...", self)
        self.worker = ImportWorker(
            source_path=source_path,
            project_name=name,
            workspace_dir=self.workspace_root,
            settings=config,
            profile_id=self.profile_combo.currentData() or "auto",
        )

        self.worker.progress.connect(self.progress_dialog.set_progress)
        self.progress_dialog.cancelled.connect(self.worker.cancel)

        self.worker.finished.connect(self._on_worker_finished)
        self.worker.error.connect(self._on_worker_error)

        self.worker.start()
        self.progress_dialog.exec()

    def _on_worker_finished(self, project: Project) -> None:
        if self.progress_dialog:
            self.progress_dialog.accept()
        self.project_created.emit(project)
        self.accept()

    def _on_worker_error(self, error_msg: str) -> None:
        if self.progress_dialog:
            self.progress_dialog.reject()
        QMessageBox.critical(self, "Import Failed", f"Failed to import presentation:\n{error_msg}")
