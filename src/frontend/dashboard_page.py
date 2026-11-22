"""Main Dashboard page for PPT Lecture Studio."""
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional, List, Dict, Any
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox, QFrame
)
from PySide6.QtCore import Qt, Signal

from src.backend.project_manager import ProjectDeleteError, ProjectManager
from src.frontend.widgets.status_badge import StatusBadge


class DashboardPage(QWidget):
    """Main dashboard displaying project overview, quick actions, and recent projects."""

    create_project_requested = Signal()
    open_project_requested = Signal()
    project_selected = Signal(str)  # project directory path
    project_deleted = Signal(str)   # project directory whose files were deleted

    REMOVE, DELETE = "remove", "delete"

    def __init__(self, workspace_root: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self.workspace_root = workspace_root or Path.cwd()
        self.pm = ProjectManager(self.workspace_root)
        # Returns the open project's folder (or None); deleting an open project is refused.
        self.current_project_dir: Callable[[], Optional[str]] = lambda: None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(20)

        # Welcome Header Banner
        banner = QFrame()
        banner.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1e3a8a, stop:1 #1e293b);
                border-radius: 12px;
                padding: 16px;
            }
        """)
        b_layout = QVBoxLayout(banner)
        b_layout.setSpacing(6)

        title = QLabel("PPT Lecture Studio")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #ffffff;")
        b_layout.addWidget(title)

        subtitle = QLabel("Transform PowerPoint presentations and slide decks into professional educational lecture videos.")
        subtitle.setStyleSheet("font-size: 14px; color: #cbd5e1;")
        b_layout.addWidget(subtitle)

        layout.addWidget(banner)

        # Quick Actions Row
        actions_row = QHBoxLayout()
        actions_row.setSpacing(16)

        self.btn_new = QPushButton("＋  Create New Project")
        self.btn_new.setObjectName("primaryBtn")
        self.btn_new.setFixedHeight(46)
        self.btn_new.setStyleSheet("font-size: 14px;")
        self.btn_new.clicked.connect(self.create_project_requested.emit)
        actions_row.addWidget(self.btn_new)

        self.btn_open = QPushButton("📂  Open Existing Project")
        self.btn_open.setFixedHeight(46)
        self.btn_open.setStyleSheet("font-size: 14px;")
        self.btn_open.clicked.connect(self.open_project_requested.emit)
        actions_row.addWidget(self.btn_open)

        actions_row.addStretch()
        layout.addLayout(actions_row)

        # Recent Projects Group
        recent_group = QGroupBox("Recent Projects")
        rg_layout = QVBoxLayout(recent_group)
        rg_layout.setContentsMargins(12, 16, 12, 12)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Project Name", "Slides", "Stage", "Last Modified", "Actions"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 150)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 200)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)   # room for styled buttons / badges
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._on_double_click)

        self.lbl_empty = QLabel("No recent projects. Create a new project or open an existing one.")
        self.lbl_empty.setStyleSheet("color: #9ca3af;")
        rg_layout.addWidget(self.lbl_empty)
        rg_layout.addWidget(self.table)
        layout.addWidget(recent_group, 1)

    @staticmethod
    def _fmt_date(iso: str) -> str:
        try:
            return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            return (iso or "")[:16].replace("T", " ")

    def refresh_projects(self) -> None:
        """Rebuild the Recent Projects list."""
        projects = self.pm.list_projects()
        self.lbl_empty.setVisible(not projects)
        self.table.setRowCount(len(projects))
        for row, p in enumerate(projects):
            proj_dir, name = p["project_dir"], p["project_name"]
            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.UserRole, proj_dir)
            name_item.setToolTip(proj_dir)
            self.table.setItem(row, 0, name_item)

            slides_item = QTableWidgetItem(f"{p['slide_count']} slides")
            slides_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, slides_item)
            self.table.setCellWidget(row, 2, StatusBadge(p.get("workflow_stage", "imported")))

            time_item = QTableWidgetItem(self._fmt_date(p.get("updated_at", "")))
            time_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, time_item)

            cell = QWidget()
            h = QHBoxLayout(cell)
            h.setContentsMargins(6, 4, 6, 4)
            h.setSpacing(6)
            btn_open = QPushButton("Open")
            btn_open.setFixedHeight(32)
            btn_open.clicked.connect(lambda _=False, d=proj_dir: self.open_project(d))
            btn_del = QPushButton("Delete…")
            btn_del.setFixedHeight(32)
            btn_del.setObjectName("dangerBtn")
            btn_del.setToolTip("Remove from this list, or delete the project and its files")
            btn_del.clicked.connect(lambda _=False, d=proj_dir, n=name: self.delete_requested(d, n))
            for b in (btn_open, btn_del):
                b.setStyleSheet("padding: 2px 10px; min-height: 0px;")
            h.addWidget(btn_open); h.addWidget(btn_del)
            self.table.setCellWidget(row, 4, cell)

    def _on_double_click(self, row: int, _col: int) -> None:
        item = self.table.item(row, 0)
        if item:
            self.open_project(item.data(Qt.UserRole))

    def open_project(self, project_dir: str) -> None:
        if not (Path(project_dir) / "project.json").is_file():
            QMessageBox.warning(self, "Project Not Found",
                                f"The project folder no longer exists:\n{project_dir}\n\nIt will be removed from the list.")
            self.pm.remove_from_recent(project_dir)
            self.refresh_projects()
            return
        self.pm.add_recent(project_dir)
        self.project_selected.emit(project_dir)

    # ------------------------------------------------------------------ delete
    def ask_delete_choice(self, name: str, project_dir: str) -> Optional[str]:
        """Returns REMOVE, DELETE or None (cancel). Overridable for tests."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Delete Project")
        box.setText(f"What do you want to do with “{name}”?")
        box.setInformativeText(f"Folder: {project_dir}")
        b_remove = box.addButton("Remove from Recent Projects", QMessageBox.AcceptRole)
        b_delete = box.addButton("Delete Project and All Files", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(b_remove)
        box.exec()
        return {b_remove: self.REMOVE, b_delete: self.DELETE}.get(box.clickedButton())

    def confirm_permanent_delete(self, name: str, project_dir: str) -> bool:
        ans = QMessageBox.warning(
            self, "Permanently Delete Project?",
            f"Permanently delete “{name}” and ALL of its files?\n\n{project_dir}\n\n"
            "Slides, narration, audio and rendered videos in this folder will be deleted. "
            "This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return ans == QMessageBox.Yes

    def delete_requested(self, project_dir: str, name: str) -> None:
        choice = self.ask_delete_choice(name, project_dir)
        if choice == self.REMOVE:
            self.pm.remove_from_recent(project_dir)
        elif choice == self.DELETE:
            cur = self.current_project_dir()
            if cur and ProjectManager._key(cur) == ProjectManager._key(project_dir):
                QMessageBox.information(self, "Project Is Open",
                                        "This project is currently open. Open a different project, then delete it.")
                return
            if not self.confirm_permanent_delete(name, project_dir):
                return
            try:
                self.pm.delete_project(project_dir)
                self.project_deleted.emit(project_dir)
            except (ProjectDeleteError, OSError) as exc:
                QMessageBox.critical(self, "Delete Failed", str(exc))
        self.refresh_projects()
