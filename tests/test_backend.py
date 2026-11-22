"""Unit tests for PPT Lecture Studio backend and workflow gates."""
import shutil
import tempfile
from pathlib import Path
import pytest

from src.models.project import Project, WorkflowStage
from src.models.slide import Slide, SlideReviewStatus
from src.models.narration import SlideNarration, NarrationStatus
from src.models.video_config import VideoConfig
from src.backend.project_manager import ProjectManager
from src.backend.workflow_manager import WorkflowManager, WorkflowError
from src.backend.slides.pdf_parser import PDFPresentationParser
from src.backend.slides.slide_renderer import SlideRenderer
from src.backend.slides.slide_manager import SlideManager
from src.backend.narration.narration_manager import NarrationManager


@pytest.fixture
def temp_workspace():
    tmp_dir = tempfile.mkdtemp(prefix="ppt_studio_test_")
    yield Path(tmp_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def sample_pdf():
    pdf_path = Path("docs/pdfs/Day1_SAP_BTP_Architecture.pdf").resolve()
    assert pdf_path.is_file(), f"Sample test PDF not found at {pdf_path}"
    return pdf_path


def test_pdf_parsing(sample_pdf):
    parser = PDFPresentationParser(sample_pdf)
    info = parser.inspect_presentation()
    assert info["slide_count"] == 29
    assert "Day1_SAP_BTP_Architecture" in info["file_name"]

    slides, summary = parser.parse_slides()
    assert len(slides) == 29
    assert summary["slide_count"] == 29
    assert summary["total_words"] > 500

    slide1 = slides[0]
    assert slide1.slide_number == 1
    assert slide1.slide_id == "slide_001"
    assert "SAP BTP" in slide1.title or "Architecture" in slide1.title or len(slide1.title) > 0
    assert slide1.review_status == SlideReviewStatus.REVIEW_REQUIRED


def test_project_lifecycle_and_persistence(temp_workspace, sample_pdf):
    pm = ProjectManager(temp_workspace)
    project = pm.create_project(
        name="SAP BTP Lecture",
        source_path=sample_pdf,
    )

    assert project.project_id == "sap_btp_lecture"
    assert Path(project.project_dir).is_dir()
    assert (Path(project.project_dir) / "project.json").is_file()
    assert (Path(project.project_dir) / project.source_file).is_file()

    # Load project back
    loaded = pm.load_project(project.project_dir)
    assert loaded.project_name == "SAP BTP Lecture"
    assert loaded.workflow_stage == WorkflowStage.IMPORTED
    assert loaded.slides_approved is False


def test_slide_rendering(temp_workspace, sample_pdf):
    pm = ProjectManager(temp_workspace)
    project = pm.create_project(name="Render Test", source_path=sample_pdf)

    parser = PDFPresentationParser(Path(project.project_dir) / project.source_file)
    slides, _ = parser.parse_slides()
    project.slides = slides[:3]  # Test rendering first 3 slides

    renderer = SlideRenderer(project.project_dir)
    rendered = renderer.render_all_slides(
        pdf_path=Path(project.project_dir) / project.source_file,
        slides=project.slides,
    )

    for slide in rendered:
        img_path = Path(project.project_dir) / slide.image_path
        thumb_path = Path(project.project_dir) / slide.thumbnail_path
        assert img_path.is_file(), f"Slide image missing: {img_path}"
        assert thumb_path.is_file(), f"Thumbnail missing: {thumb_path}"
        assert img_path.stat().st_size > 5000
        assert thumb_path.stat().st_size > 1000


def test_slide_manager_and_approval_invalidation(temp_workspace, sample_pdf):
    pm = ProjectManager(temp_workspace)
    project = pm.create_project(name="Manager Test", source_path=sample_pdf)
    project.slides = [
        Slide(slide_id="slide_001", slide_number=1, title="Intro", review_status=SlideReviewStatus.REVIEW_REQUIRED),
        Slide(slide_id="slide_002", slide_number=2, title="Architecture", review_status=SlideReviewStatus.REVIEW_REQUIRED),
    ]

    sm = SlideManager(project)
    sm.approve_slide("slide_001")
    sm.approve_slide("slide_002")
    assert project.get_slide_by_id("slide_001").review_status == SlideReviewStatus.APPROVED
    assert project.get_slide_by_id("slide_002").review_status == SlideReviewStatus.APPROVED

    wm = WorkflowManager(project)
    ok, msg = wm.approve_entire_presentation()
    assert ok is True
    assert project.slides_approved is True
    assert project.workflow_stage == WorkflowStage.SLIDES_APPROVED

    # Modifying a slide must invalidate presentation approval
    sm.update_slide("slide_001", title="New Title")
    assert project.get_slide_by_id("slide_001").review_status == SlideReviewStatus.EDITED
    assert project.slides_approved is False
    # Stage must roll back to slide review
    wm.invalidate_slide_approval()
    assert project.workflow_stage == WorkflowStage.SLIDE_REVIEW


def test_no_workflow_gates(temp_workspace, sample_pdf):
    """Approvals are optional: nothing is blocked."""
    pm = ProjectManager(temp_workspace)
    project = pm.create_project(name="No Gate Test", source_path=sample_pdf)
    project.slides = [
        Slide(slide_id="slide_001", slide_number=1, review_status=SlideReviewStatus.REVIEW_REQUIRED),
        Slide(slide_id="slide_002", slide_number=2, review_status=SlideReviewStatus.REJECTED),
    ]
    wm = WorkflowManager(project)
    for stage in (WorkflowStage.NARRATION_PREPARATION, WorkflowStage.VIDEO_EXPORT):
        assert wm.can_transition_to(stage)[0] is True

    ok, _ = wm.approve_entire_presentation()      # approves everything in one go
    assert ok is True and project.slides_approved is True
    assert all(s.review_status == SlideReviewStatus.APPROVED for s in project.slides)
    wm.transition_to(WorkflowStage.VIDEO_EXPORT)
    assert project.workflow_stage == WorkflowStage.VIDEO_EXPORT


def test_narration_manager_and_invalidation(temp_workspace, sample_pdf):
    pm = ProjectManager(temp_workspace)
    project = pm.create_project(name="Narration Test", source_path=sample_pdf)
    project.slides = [
        Slide(slide_id="slide_001", slide_number=1, title="Cloud Platform", original_text="Point 1\nPoint 2"),
    ]
    nm = NarrationManager(project)
    narrations = nm.generate_initial_narrations()
    assert len(narrations) == 1
    assert "Cloud Platform" in narrations[0].script
    assert narrations[0].word_count > 5
    assert narrations[0].status == NarrationStatus.DRAFT

    # Simulate approved presentation and approved narration
    project.slides_approved = True
    nm.approve_narration("slide_001")
    project.narration_approved = True
    narrations[0].audio_status = "ready"
    narrations[0].audio_path = "audio/slide_001.wav"

    # Editing narration resets approval but keeps existing audio until regenerated
    wm = WorkflowManager(project)
    wm.invalidate_narration_script("slide_001")
    assert narrations[0].status == NarrationStatus.EDITED
    assert narrations[0].audio_path == "audio/slide_001.wav"
    assert project.narration_approved is False
