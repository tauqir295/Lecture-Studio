"""Dashboard Recent Projects: list, open, remove-from-list, safe permanent delete; app icon files."""
from pathlib import Path

import pytest

from src.backend.project_manager import ProjectDeleteError, ProjectManager
from src.models.project import Project

ROOT = Path(__file__).resolve().parents[1]


def _make(pm: ProjectManager, name: str, parent: Path = None) -> Path:
    d = (parent or pm.projects_dir) / name
    d.mkdir(parents=True)
    pm.save_project(Project(project_id=name, project_name=name.title(), project_dir=str(d)))
    (d / "audio").mkdir(exist_ok=True)
    (d / "audio" / "slide_001.wav").write_bytes(b"x")
    return d


# ------------------------------------------------------------------ backend
def test_list_remove_and_readd(tmp_path):
    pm = ProjectManager(tmp_path)
    a, b = _make(pm, "alpha"), _make(pm, "beta")
    names = [p["project_name"] for p in pm.list_projects()]
    assert names == ["Beta", "Alpha"]                     # newest first
    assert all(p["updated_at"] for p in pm.list_projects())

    pm.remove_from_recent(a)
    assert [p["project_name"] for p in pm.list_projects()] == ["Beta"]
    assert (a / "project.json").is_file() and (a / "audio" / "slide_001.wav").is_file()   # files kept
    assert [p["project_name"] for p in ProjectManager(tmp_path).list_projects()] == ["Beta"]  # persisted

    pm.add_recent(a)                                       # opening it again brings it back
    assert {p["project_name"] for p in pm.list_projects()} == {"Alpha", "Beta"}


def test_external_projects_are_remembered(tmp_path):
    pm = ProjectManager(tmp_path / "ws")
    ext = _make(pm, "outside", parent=tmp_path / "elsewhere")
    assert pm.list_projects() == []
    pm.add_recent(ext)
    assert [p["project_name"] for p in pm.list_projects()] == ["Outside"]
    pm.remove_from_recent(ext)
    assert pm.list_projects() == [] and ext.is_dir()


def test_corrupt_recent_file_is_ignored(tmp_path):
    pm = ProjectManager(tmp_path)
    _make(pm, "alpha")
    (pm.projects_dir / ".recent.json").write_text("{not json")
    assert [p["project_name"] for p in pm.list_projects()] == ["Alpha"]


def test_delete_project_removes_only_that_folder(tmp_path):
    pm = ProjectManager(tmp_path)
    a, b = _make(pm, "alpha"), _make(pm, "beta")
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    link = a / "link_to_outside"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        link = None                                        # symlinks unavailable (e.g. Windows without rights)
    pm.delete_project(a)
    assert not a.exists()
    assert b.is_dir() and outside.read_text() == "keep"    # link removed, target untouched
    assert [p["project_name"] for p in pm.list_projects()] == ["Beta"]


@pytest.mark.parametrize("which", ["workspace", "projects_dir", "home", "no_json", "missing"])
def test_delete_refuses_unsafe_targets(tmp_path, which):
    pm = ProjectManager(tmp_path)
    _make(pm, "alpha")
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "keep.txt").write_text("x")
    target = {"workspace": tmp_path, "projects_dir": pm.projects_dir, "home": Path.home(),
              "no_json": plain, "missing": tmp_path / "nope"}[which]
    with pytest.raises(ProjectDeleteError):
        pm.delete_project(target)
    assert (pm.projects_dir / "alpha" / "project.json").is_file() and (plain / "keep.txt").is_file()


def test_delete_refuses_symlinked_project(tmp_path):
    pm = ProjectManager(tmp_path / "ws")
    real = _make(pm, "real", parent=tmp_path / "data")
    link = pm.projects_dir / "linked"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    with pytest.raises(ProjectDeleteError):
        pm.delete_project(link)
    assert (real / "project.json").is_file()


# ------------------------------------------------------------------ dashboard UI
@pytest.fixture
def dash(qapp, tmp_path):
    from src.frontend.dashboard_page import DashboardPage
    d = DashboardPage(tmp_path)
    return d


def test_dashboard_lists_name_and_date_and_opens(dash):
    a = _make(dash.pm, "alpha")
    dash.refresh_projects()
    assert dash.table.rowCount() == 1 and not dash.lbl_empty.isVisibleTo(dash)
    assert dash.table.item(0, 0).text() == "Alpha"
    assert len(dash.table.item(0, 3).text()) == 16         # YYYY-MM-DD HH:MM
    opened = []
    dash.project_selected.connect(opened.append)
    dash._on_double_click(0, 0)
    assert opened == [str(a)]


def test_dashboard_remove_from_recent_keeps_files(dash):
    a = _make(dash.pm, "alpha")
    dash.refresh_projects()
    dash.ask_delete_choice = lambda n, d: dash.REMOVE
    dash.delete_requested(str(a), "Alpha")
    assert dash.table.rowCount() == 0 and a.is_dir()


def test_dashboard_delete_needs_confirmation(dash):
    a = _make(dash.pm, "alpha")
    dash.refresh_projects()
    dash.ask_delete_choice = lambda n, d: dash.DELETE
    dash.confirm_permanent_delete = lambda n, d: False      # user says No
    dash.delete_requested(str(a), "Alpha")
    assert a.is_dir() and dash.table.rowCount() == 1

    deleted = []
    dash.project_deleted.connect(deleted.append)
    dash.confirm_permanent_delete = lambda n, d: True
    dash.delete_requested(str(a), "Alpha")
    assert not a.exists() and dash.table.rowCount() == 0 and deleted == [str(a)]


def test_dashboard_cancel_and_open_project_guard(dash, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    a = _make(dash.pm, "alpha")
    dash.refresh_projects()
    dash.ask_delete_choice = lambda n, d: None              # cancel
    dash.delete_requested(str(a), "Alpha")
    assert a.is_dir() and dash.table.rowCount() == 1

    dash.current_project_dir = lambda: str(a)               # open project cannot be deleted
    dash.ask_delete_choice = lambda n, d: dash.DELETE
    dash.confirm_permanent_delete = lambda n, d: True
    dash.delete_requested(str(a), "Alpha")
    assert a.is_dir()


def test_dashboard_reports_delete_errors(dash, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a[2]))
    a = _make(dash.pm, "alpha")
    (a / "project.json").unlink()                           # no longer a project folder
    dash.ask_delete_choice = lambda n, d: dash.DELETE
    dash.confirm_permanent_delete = lambda n, d: True
    dash.delete_requested(str(a), "Alpha")
    assert shown and "project.json" in shown[0] and a.is_dir()


def test_open_missing_project_drops_entry(dash, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    gone = _make(dash.pm, "gone", parent=dash.workspace_root / "ext")
    dash.pm.add_recent(gone)
    import shutil
    shutil.rmtree(gone)
    opened = []
    dash.project_selected.connect(opened.append)
    dash.open_project(str(gone))
    assert opened == [] and dash.pm._read_recent()["external"] == []


# ------------------------------------------------------------------ icons
def test_platform_icons_exist_and_load(qapp):
    from PIL import Image
    icons = ROOT / "assets" / "icons"
    ico = Image.open(icons / "lecture-studio.ico")
    assert (256, 256) in ico.info["sizes"] and (16, 16) in ico.info["sizes"]
    assert Image.open(icons / "lecture-studio.icns").size == (1024, 1024)
    for s in (16, 32, 48, 128, 256, 512):
        assert Image.open(icons / "hicolor" / f"{s}x{s}" / "apps" / "lecture-studio.png").size == (s, s)
    import main
    assert not main.app_icon(ROOT).isNull()
    assert (ROOT / "packaging" / "linux" / "lecture-studio.desktop").read_text().count("Icon=lecture-studio") == 1
