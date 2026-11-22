"""Test the background ImportWorker thread."""
import shutil
import tempfile
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication

from src.backend.workers.import_worker import ImportWorker
from src.models.project import WorkflowStage


@pytest.fixture
def temp_workspace():
    tmp_dir = tempfile.mkdtemp(prefix="ppt_studio_worker_")
    yield Path(tmp_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_import_worker_execution(temp_workspace):
    # Ensure QApplication exists
    app = QApplication.instance() or QApplication([])

    pdf_path = Path("docs/pdfs/Day1_SAP_BTP_Architecture.pdf").resolve()
    assert pdf_path.is_file()

    worker = ImportWorker(
        source_path=pdf_path,
        project_name="Worker Test Project",
        workspace_dir=temp_workspace,
    )

    progress_events = []
    finished_projects = []
    error_events = []

    worker.progress.connect(lambda pct, msg: progress_events.append((pct, msg)))
    worker.finished.connect(lambda p: finished_projects.append(p))
    worker.error.connect(lambda err: error_events.append(err))

    # Run synchronously in test
    worker.run()

    assert not error_events, f"Errors occurred: {error_events}"
    assert len(finished_projects) == 1
    proj = finished_projects[0]
    assert proj.project_name == "Worker Test Project"
    assert proj.slide_count == 29
    assert proj.workflow_stage == WorkflowStage.SLIDE_REVIEW
    assert len(proj.slides) == 29
    assert len(proj.narrations) == 29
    assert len(progress_events) >= 5

    # Check slide files exist on disk
    slide1 = proj.slides[0]
    assert (Path(proj.project_dir) / slide1.image_path).is_file()
    assert (Path(proj.project_dir) / slide1.thumbnail_path).is_file()
