"""GUI and Frontend integration tests running on headless Qt."""
import os
import shutil
import tempfile
from pathlib import Path
import pytest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt

from src.models.project import Project, WorkflowStage
from src.models.slide import Slide, SlideReviewStatus
from src.models.narration import SlideNarration, NarrationStatus
from src.backend.project_manager import ProjectManager
from src.backend.workflow_manager import WorkflowManager
from src.frontend.main_window import MainWindow
from src.frontend.slide_studio import SlideStudio
from src.frontend.narration_studio import NarrationStudio
from src.frontend.settings_page import SettingsPage


@pytest.fixture(scope="session")
def qapp():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    yield app


@pytest.fixture
def temp_workspace():
    tmp_dir = tempfile.mkdtemp(prefix="ppt_gui_test_")
    yield Path(tmp_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def sample_project(temp_workspace):
    pm = ProjectManager(temp_workspace)
    pdf_path = Path("docs/pdfs/Day1_SAP_BTP_Architecture.pdf").resolve()
    project = pm.create_project(name="GUI Test Project", source_path=pdf_path)

    # Populate 3 sample slides
    s1 = Slide(slide_id="slide_001", slide_number=1, title="Intro Slide", original_text="Point A\nPoint B", review_status=SlideReviewStatus.REVIEW_REQUIRED)
    s2 = Slide(slide_id="slide_002", slide_number=2, title="Architecture", original_text="Point C\nPoint D", review_status=SlideReviewStatus.REVIEW_REQUIRED)
    s3 = Slide(slide_id="slide_003", slide_number=3, title="Summary", original_text="Point E\nPoint F", review_status=SlideReviewStatus.REVIEW_REQUIRED)

    project.slides = [s1, s2, s3]
    project.slide_count = 3
    project.narrations = [
        SlideNarration(slide_id="slide_001", slide_number=1, script="Welcome to the intro.", status=NarrationStatus.DRAFT),
        SlideNarration(slide_id="slide_002", slide_number=2, script="Here is the architecture.", status=NarrationStatus.DRAFT),
        SlideNarration(slide_id="slide_003", slide_number=3, script="Finally the summary.", status=NarrationStatus.DRAFT),
    ]
    pm.save_project(project)
    return project


def test_main_window_init(qapp, temp_workspace):
    window = MainWindow(workspace_root=temp_workspace)
    assert window.windowTitle() == "PPT Lecture Studio"
    assert window.sidebar.count() == 6
    assert window.pages.count() == 6
    window.close()


def test_slide_studio_interactions_and_approval(qapp, sample_project):
    studio = SlideStudio()
    studio.load_project(sample_project)
    assert studio.navigator.list_widget.count() == 3
    assert studio.editor.title_edit.text() == "Intro Slide"

    studio._approve_slide("slide_001")
    assert sample_project.get_slide_by_id("slide_001").review_status == SlideReviewStatus.APPROVED
    assert sample_project.get_slide_by_id("slide_002").review_status == SlideReviewStatus.REVIEW_REQUIRED

    # No gate: approving the presentation works at any time and approves all slides
    studio._approve_presentation()
    assert sample_project.slides_approved is True
    assert all(s.review_status == SlideReviewStatus.APPROVED for s in sample_project.slides)
    assert sample_project.workflow_stage == WorkflowStage.SLIDES_APPROVED


def test_narration_studio_editing_and_gate(qapp, sample_project):
    with patch.object(QMessageBox, "information"), patch.object(QMessageBox, "warning"):
        # No gate: narration can be approved even though slides are not
        studio = NarrationStudio()
        studio.load_project(sample_project)
        assert sample_project.slides_approved is False
        assert studio.script_list.count() == 3

        # Edit narration script for slide 1
        studio.script_edit.setText("This is an updated custom narration script.")
        narration1 = sample_project.get_narration_by_id("slide_001")
        assert narration1.status == NarrationStatus.EDITED
        assert "updated custom" in narration1.script
        assert narration1.word_count == 7

        # Approve all scripts in one click (no per-script approval needed)
        studio._approve_all_narrations()
        assert sample_project.narration_approved is True
        assert all(n.status == NarrationStatus.APPROVED for n in sample_project.narrations)


def test_settings_page_theme_switch(qapp):
    settings = SettingsPage()
    emitted = []
    settings.theme_changed.connect(lambda t: emitted.append(t))

    settings.theme_combo.setCurrentIndex(1)  # Light theme
    assert emitted == ["light"]

    settings.theme_combo.setCurrentIndex(0)  # Dark theme
    assert emitted == ["light", "dark"]


def test_slide_studio_approve_selected_slides(qapp, sample_project):
    studio = SlideStudio()
    studio.load_project(sample_project)
    lw = studio.navigator.list_widget
    lw.clearSelection()
    lw.item(0).setSelected(True)
    lw.item(2).setSelected(True)

    assert studio.navigator.get_selected_slide_ids() == ["slide_001", "slide_003"]
    assert studio.btn_approve_selected.isEnabled()
    assert "(2)" in studio.btn_approve_selected.text()

    studio._approve_selected_slides()
    st = {s.slide_id: s.review_status for s in sample_project.slides}
    assert st["slide_001"] == st["slide_003"] == SlideReviewStatus.APPROVED
    assert st["slide_002"] == SlideReviewStatus.REVIEW_REQUIRED
    assert sample_project.slides_approved is False  # presentation gate untouched
    assert "2 / 3" in studio.lbl_approval_summary.text()


def test_slide_studio_approve_all_slides(qapp, sample_project):
    studio = SlideStudio()
    studio.load_project(sample_project)
    studio._approve_all_slides()          # no confirmation dialogs
    assert all(s.review_status == SlideReviewStatus.APPROVED for s in sample_project.slides)
    assert sample_project.slides_approved is True
    reloaded = ProjectManager(sample_project.project_dir).load_project(sample_project.project_dir)
    assert all(s.review_status == SlideReviewStatus.APPROVED for s in reloaded.slides)


def test_video_studio_has_no_approval_gate(qapp, sample_project):
    from src.frontend.video_studio import VideoStudio
    from src.backend.video.pipeline import missing_tools
    assert sample_project.slides_approved is False and sample_project.narration_approved is False
    video = VideoStudio()
    video.load_project(sample_project)
    assert video.gate_problems() == missing_tools()
    if not missing_tools():
        assert video.btn_export.isEnabled()
        assert "Ready to generate" in video.lbl_gate_info.text()
