"""Main Window for PPT Lecture Studio desktop application."""
from pathlib import Path
from typing import Optional
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget,
    QStackedWidget, QLabel, QFileDialog, QMessageBox, QStatusBar
)
from PySide6.QtGui import QAction, QKeySequence, QIcon
from PySide6.QtCore import Qt

from src.models.project import Project
from src.backend.project_manager import ProjectManager
from src.frontend.styles import DARK_THEME, LIGHT_THEME
from src.frontend.dashboard_page import DashboardPage
from src.frontend.project_wizard import ProjectWizard
from src.frontend.import_analysis_page import ImportAnalysisPage
from src.frontend.slide_studio import SlideStudio
from src.frontend.narration_studio import NarrationStudio
from src.frontend.video_studio import VideoStudio
from src.frontend.settings_page import SettingsPage
from src.utils.logging_config import setup_logger

logger = setup_logger("main_window")


class MainWindow(QMainWindow):
    """Primary application shell providing sidebar navigation, page hosting, and project coordination."""

    def __init__(self, workspace_root: Optional[Path] = None):
        super().__init__()
        self.workspace_root = workspace_root or Path.cwd()
        self.pm = ProjectManager(self.workspace_root)
        self.current_project: Optional[Project] = None

        self.setWindowTitle("PPT Lecture Studio")
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)

        self._build_menu()
        self._build_ui()
        self._build_status_bar()
        self.apply_theme("dark")

    def _build_menu(self) -> None:
        menubar = self.menuBar()
        menubar.setNativeMenuBar(False)

        # File Menu
        file_menu = menubar.addMenu("&File")

        act_new = QAction("&New Project...", self)
        act_new.setShortcut(QKeySequence.New)
        act_new.triggered.connect(self._open_new_project_wizard)
        file_menu.addAction(act_new)

        act_open = QAction("&Open Project...", self)
        act_open.setShortcut(QKeySequence.Open)
        act_open.triggered.connect(self._open_project_dialog)
        file_menu.addAction(act_open)

        act_save = QAction("&Save Project", self)
        act_save.setShortcut(QKeySequence.Save)
        act_save.triggered.connect(self._save_current_project)
        file_menu.addAction(act_save)

        file_menu.addSeparator()

        act_exit = QAction("E&xit", self)
        act_exit.setShortcut(QKeySequence.Quit)
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # View Menu
        view_menu = menubar.addMenu("&View")

        act_dark = QAction("&Dark Theme", self)
        act_dark.triggered.connect(lambda: self.apply_theme("dark"))
        view_menu.addAction(act_dark)

        act_light = QAction("&Light Theme", self)
        act_light.triggered.connect(lambda: self.apply_theme("light"))
        view_menu.addAction(act_light)

        # Help Menu
        help_menu = menubar.addMenu("&Help")
        act_about = QAction("&About PPT Lecture Studio", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Left Sidebar Navigation
        sidebar_container = QWidget()
        sidebar_container.setFixedWidth(230)
        sidebar_container.setStyleSheet("background-color: #17171d; border-right: 1px solid #282834;")
        sb_layout = QVBoxLayout(sidebar_container)
        sb_layout.setContentsMargins(12, 16, 12, 16)
        sb_layout.setSpacing(10)

        app_title = QLabel("PPT Lecture Studio")
        app_title.setStyleSheet("font-size: 17px; font-weight: bold; color: #60a5fa; padding: 6px;")
        sb_layout.addWidget(app_title)

        self.sidebar = QListWidget()
        self.sidebar.setFocusPolicy(Qt.NoFocus)
        nav_items = [
            "📊  Dashboard",
            "🔍  Analysis",
            "🖼️  Slide Studio",
            "🎙️  Narration Studio",
            "🎬  Video Studio",
            "⚙️  Settings",
        ]
        self.sidebar.addItems(nav_items)
        self.sidebar.currentRowChanged.connect(self._on_navigation_changed)
        sb_layout.addWidget(self.sidebar, 1)

        layout.addWidget(sidebar_container)

        # Main Central Stacked Pages
        self.pages = QStackedWidget()

        self.dashboard_page = DashboardPage(self.workspace_root)
        self.dashboard_page.create_project_requested.connect(self._open_new_project_wizard)
        self.dashboard_page.open_project_requested.connect(self._open_project_dialog)
        self.dashboard_page.project_selected.connect(self._load_project_from_dir)
        self.dashboard_page.current_project_dir = (
            lambda: self.current_project.project_dir if self.current_project else None)
        self.pages.addWidget(self.dashboard_page)

        self.analysis_page = ImportAnalysisPage()
        self.analysis_page.proceed_to_slide_studio.connect(lambda: self.navigate_to(2))
        self.pages.addWidget(self.analysis_page)

        self.slide_studio = SlideStudio()
        self.slide_studio.presentation_approved.connect(self._on_slides_approved)
        self.pages.addWidget(self.slide_studio)

        self.narration_studio = NarrationStudio()
        self.narration_studio.narration_approved.connect(self._on_narration_approved)
        self.pages.addWidget(self.narration_studio)

        self.video_studio = VideoStudio()
        self.pages.addWidget(self.video_studio)

        self.settings_page = SettingsPage()
        self.settings_page.theme_changed.connect(self.apply_theme)
        self.pages.addWidget(self.settings_page)

        layout.addWidget(self.pages, 1)
        self.setCentralWidget(central)

        # Start at Dashboard
        self.sidebar.setCurrentRow(0)
        self.dashboard_page.refresh_projects()

    def _build_status_bar(self) -> None:
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.status_project_lbl = QLabel("No project loaded")
        self.status_project_lbl.setStyleSheet("color: #9ca3af; padding-left: 10px;")
        self.status_bar.addWidget(self.status_project_lbl)

        self.status_gate_lbl = QLabel("Ready")
        self.status_gate_lbl.setStyleSheet("color: #60a5fa; font-weight: bold; padding-right: 15px;")
        self.status_bar.addPermanentWidget(self.status_gate_lbl)

    def apply_theme(self, theme: str) -> None:
        qss = DARK_THEME if theme == "dark" else LIGHT_THEME
        self.setStyleSheet(qss)

    def navigate_to(self, index: int) -> None:
        self.sidebar.setCurrentRow(index)

    def _on_navigation_changed(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        if index == 0:
            self.dashboard_page.refresh_projects()
        elif self.current_project is not None:
            # Studios share one Project object; re-read its state so gates are never stale.
            if index == 3:
                self.narration_studio.load_project(self.current_project)
            elif index == 4:
                self.video_studio.load_project(self.current_project)

    def _open_new_project_wizard(self) -> None:
        wizard = ProjectWizard(self.workspace_root, self)
        wizard.project_created.connect(self.load_project)
        wizard.exec()

    def _open_project_dialog(self) -> None:
        projects_dir = str(self.workspace_root / "Projects")
        path = QFileDialog.getExistingDirectory(self, "Open Project Directory", projects_dir)
        if path:
            self._load_project_from_dir(path)

    def _load_project_from_dir(self, directory: str) -> None:
        try:
            proj = self.pm.load_project(directory)
            self.pm.add_recent(directory)
            self.load_project(proj)
        except Exception as exc:
            QMessageBox.critical(self, "Error Loading Project", f"Could not open project:\n{exc}")

    def load_project(self, project: Project) -> None:
        self.current_project = project
        self.status_project_lbl.setText(f"Project: {project.project_name} ({project.slide_count} slides)")
        self.status_gate_lbl.setText(f"Stage: {project.workflow_stage.value.replace('_', ' ').title()}")

        # Load into pages
        self.analysis_page.load_project(project)
        self.slide_studio.load_project(project)
        self.narration_studio.load_project(project)
        self.video_studio.load_project(project)

        # Switch to Slide Studio
        self.navigate_to(2)
        logger.info(f"Loaded project '{project.project_name}' into UI.")

    def _on_slides_approved(self) -> None:
        if self.current_project:
            self.narration_studio.load_project(self.current_project)
            self.video_studio.load_project(self.current_project)
            self.status_gate_lbl.setText("Stage: Narration Preparation")
            self.navigate_to(3)  # Switch to Narration Studio

    def _on_narration_approved(self) -> None:
        if self.current_project:
            self.video_studio.load_project(self.current_project)
            self.status_gate_lbl.setText("Stage: Video Preview Ready")
            self.navigate_to(4)  # Switch to Video Studio

    def _save_current_project(self) -> None:
        if self.current_project:
            self.pm.save_project(self.current_project)
            self.status_bar.showMessage("Project saved successfully.", 3000)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About PPT Lecture Studio",
            "<h3>PPT Lecture Studio v1.0.0</h3>"
            "<p>A modular, offline-first Python desktop application that transforms "
            "PowerPoint presentation slide decks into reviewed, narrated educational video lectures.</p>"
            "<p><b>Workflow:</b> Slide review → Narration review → MP4 video generation. Approvals are optional status markers.</p>",
        )
