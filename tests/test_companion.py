"""Tests for companion lecture packages (narration + related files next to a PDF)."""
import json
import shutil
import tempfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.backend.companion import FORMAT, find_companion
from src.backend.project_manager import ProjectManager
from src.backend.workers.import_worker import ImportWorker
from src.models.narration import NarrationStatus

SRC_PDF = Path("docs/pdfs/Day1_SAP_BTP_Architecture.pdf").resolve()


@pytest.fixture
def tmp():
    d = Path(tempfile.mkdtemp(prefix="ppt_companion_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _make_package(folder: Path, n_slides: int = 29) -> Path:
    pkg = folder / "pkg"
    pkg.mkdir()
    pdf = pkg / "Deck.pdf"
    shutil.copy(SRC_PDF, pdf)
    (pkg / "narration.md").write_text("# narration\n")
    (pkg / "technical_review.md").write_text("# review\n")
    manifest = {
        "format": FORMAT, "deck_title": "Test Deck", "pdf": "Deck.pdf", "words_per_minute": 150,
        "files": {"narration": "narration.md", "technical_review": "technical_review.md",
                  "missing": "nope.md"},
        "slides": [{"slide_number": i, "title": f"Title {i}", "section": "S",
                    "narration": f"Narration for slide {i} with some words."} for i in range(1, n_slides + 1)],
    }
    (pkg / "Deck.json").write_text(json.dumps(manifest))
    return pdf


def test_find_companion_detects_and_skips_missing_files(tmp):
    pdf = _make_package(tmp)
    pkg = find_companion(pdf)
    assert pkg is not None
    assert len(pkg.slides) == 29
    assert set(pkg.files) == {"narration", "technical_review"}


def test_find_companion_none_for_plain_pdf():
    assert find_companion(SRC_PDF) is None


def _run_import(pdf, workspace):
    QApplication.instance() or QApplication([])
    worker = ImportWorker(source_path=pdf, project_name="Companion Test", workspace_dir=workspace)
    done, errors = [], []
    worker.finished.connect(done.append)
    worker.error.connect(errors.append)
    worker.run()
    assert not errors, errors
    return done[0]


def test_import_applies_companion_and_persists(tmp):
    pdf = _make_package(tmp)
    proj = _run_import(pdf, tmp / "ws")
    root = Path(proj.project_dir)

    assert len(proj.narrations) == 29
    assert proj.narrations[0].script == "Narration for slide 1 with some words."
    assert all(n.status == NarrationStatus.DRAFT for n in proj.narrations)  # imported as drafts
    assert proj.slides[4].title == "Title 5"
    assert (root / "narration" / "narration.md").is_file()
    assert (root / "companion" / "technical_review.md").is_file()
    assert (root / "companion" / "Deck.json").is_file()

    reloaded = ProjectManager(tmp / "ws").load_project(root)
    assert reloaded.companion["files"]["technical_review"] == "companion/technical_review.md"
    assert reloaded.narrations[3].script.startswith("Narration for slide 4")


def test_import_fills_gaps_when_package_is_shorter(tmp):
    pdf = _make_package(tmp, n_slides=10)
    proj = _run_import(pdf, tmp / "ws")
    assert len(proj.narrations) == 29  # 10 from package, 19 auto-drafted
    assert proj.companion["warnings"]


# ------------------------------------------------------------------ manifest file naming
def _manifest(pdf_name=None):
    d = {"format": FORMAT, "slides": [{"slide_number": 1, "narration": "Hi."}]}
    if pdf_name:
        d["pdf"] = pdf_name
    return json.dumps(d)


def test_manifest_named_after_pdf_is_found(tmp):
    pdf = tmp / "intro.pdf"
    shutil.copy(SRC_PDF, pdf)
    (tmp / "intro.json").write_text(_manifest())               # <pdf-stem>.json, no "pdf" field needed
    assert find_companion(pdf).manifest_path.name == "intro.json"


def test_unrelated_json_files_are_ignored(tmp):
    pdf = tmp / "intro.pdf"
    shutil.copy(SRC_PDF, pdf)
    (tmp / "intro.json").write_text(json.dumps({"some": "config"}))       # no format marker
    (tmp / "package.json").write_text(json.dumps({"name": "x"}))
    (tmp / "other.json").write_text(_manifest("another.pdf"))             # manifest for a different PDF
    (tmp / "broken.json").write_text("{not json")
    assert find_companion(pdf) is None


def test_other_manifest_names_work_when_they_name_the_pdf(tmp):
    pdf = tmp / "intro.pdf"
    shutil.copy(SRC_PDF, pdf)
    (tmp / "course-notes.json").write_text(_manifest("intro.pdf"))
    (tmp / "intro.lecture.json").write_text(_manifest("intro.pdf"))       # older naming still accepted this way
    assert find_companion(pdf).manifest_path.name == "course-notes.json"  # sorted; first valid one wins
