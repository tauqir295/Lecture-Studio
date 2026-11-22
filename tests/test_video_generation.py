"""Slide-range / duration planning, Video Studio controls and the real render pipeline."""
import json
import shutil
import tempfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.backend.video.pipeline import generate_video, list_generated, missing_tools
from src.backend.video.timing import RenderSettings, plan_timing, validate_range
from src.models.narration import NarrationStatus, SlideNarration
from src.models.slide import Slide, SlideReviewStatus

WORDS = "word " * 160  # 160 words = 60 s at 160 wpm, speed 1.0


def _deck(n=10, words=WORDS):
    slides = [Slide(slide_id=f"s{i}", slide_number=i, title=f"T{i}") for i in range(1, n + 1)]
    narr = [SlideNarration(slide_id=f"s{i}", slide_number=i, script=words) for i in range(1, n + 1)]
    return slides, narr


# ------------------------------------------------------------------ range
@pytest.mark.parametrize("a,b,ok", [(1, 20, True), (21, 40, True), (15, 35, True), (50, 73, True),
                                    (1, 73, True), (40, 21, False), (0, 5, False), (70, 74, False)])
def test_validate_range(a, b, ok):
    assert (validate_range(a, b, 73) is None) is ok


def test_plan_respects_range():
    slides, narr = _deck(10)
    plan = plan_timing(slides, narr, RenderSettings(start=3, end=6))
    assert [t.slide_number for t in plan.slides] == [3, 4, 5, 6]


def test_invalid_range_raises():
    slides, narr = _deck(5)
    with pytest.raises(ValueError):
        plan_timing(slides, narr, RenderSettings(start=4, end=2))


# ------------------------------------------------------------------ timing priorities
def cfg(**kw):
    base = dict(start=1, end=10, base_wpm=160, reading_seconds=1.0, min_slide_seconds=3.0, transition_seconds=0.5,
                max_extra_hold=20.0, min_speed=0.85, max_speed=1.2)
    base.update(kw)
    return RenderSettings(**base)


def test_natural_length_follows_narration():
    slides, narr = _deck(10)
    plan = plan_timing(slides, narr, cfg())
    assert plan.total_seconds == pytest.approx(10 * (60 + 1) + 9 * 0.5)   # no transition into slide 1
    assert plan.speed == 1.0 and plan.feasible


def test_longer_target_uses_display_time_before_speed():
    slides, narr = _deck(10)
    plan = plan_timing(slides, narr, cfg(target_seconds=750))
    assert plan.feasible and plan.speed == 1.0            # priority 4 before 5
    assert plan.total_seconds == pytest.approx(750, abs=0.5)
    assert all(t.narration_seconds == pytest.approx(60) for t in plan.slides)


def test_shorter_target_shrinks_holds_then_speeds_up():
    slides, narr = _deck(10)
    plan = plan_timing(slides, narr, cfg(target_seconds=560))
    assert plan.feasible and 1.0 < plan.speed <= 1.2
    assert plan.total_seconds == pytest.approx(560, abs=0.5)
    assert any("speed adjusted" in w for w in plan.warnings)


def test_unrealistic_target_warns_and_never_cuts_narration():
    slides, narr = _deck(10)
    plan = plan_timing(slides, narr, cfg(target_seconds=120))
    assert not plan.feasible
    assert any("too short" in w for w in plan.warnings)
    assert all(t.words == 160 for t in plan.slides)        # all words kept
    assert plan.total_seconds >= plan.min_achievable - 0.5


def test_speed_locked_when_adjustment_disabled():
    slides, narr = _deck(10)
    plan = plan_timing(slides, narr, cfg(target_seconds=560, allow_speed_adjust=False))
    assert plan.speed == 1.0 and not plan.feasible


def test_manual_timing_extends_slides_with_long_narration():
    slides, narr = _deck(3)
    plan = plan_timing(slides, narr, cfg(end=3, auto_sync=False, fixed_slide_seconds=30))
    assert all(t.display_seconds >= t.narration_seconds for t in plan.slides)
    assert any("longer than the fixed slide time" in w for w in plan.warnings)


def test_minimum_display_time_for_short_slides():
    slides, narr = _deck(2, words="hi")
    plan = plan_timing(slides, narr, cfg(end=2, min_slide_seconds=5, reading_seconds=0))
    assert all(t.narration_seconds + t.hold_seconds >= 5 - 1e-6 for t in plan.slides)


# ------------------------------------------------------------------ Video Studio UI
@pytest.fixture
def approved_project(tmp_path):
    from src.backend.project_manager import ProjectManager
    pm = ProjectManager(tmp_path)
    proj = pm.create_project("Vid", Path("docs/pdfs/Day1_SAP_BTP_Architecture.pdf").resolve())
    slides, narr = _deck(12)
    for s in slides:
        s.review_status = SlideReviewStatus.APPROVED
    for n in narr:
        n.status = NarrationStatus.APPROVED
    proj.slides, proj.narrations = slides, narr
    proj.slides_approved = proj.narration_approved = True
    return proj


def test_video_studio_range_and_estimate(qapp, approved_project):
    from src.frontend.video_studio import VideoStudio
    v = VideoStudio()
    v.load_project(approved_project)
    assert v.spin_to.value() == 12 and "Selected: 12" in v.lbl_counts.text()

    v.spin_from.setValue(4); v.spin_to.setValue(7)
    assert "Selected: 4" in v.lbl_counts.text()
    assert v.timeline_table.rowCount() == 4
    s = v.current_settings()
    assert (s.start, s.end) == (4, 7)

    v.spin_from.setValue(9)                         # 9 > 7 -> invalid
    assert "must not be greater" in v.lbl_range_error.text()
    assert not v.btn_export.isEnabled()

    v.spin_from.setValue(1); v.spin_to.setValue(12)
    v.combo_target.setCurrentIndex(1)               # 10 minutes for ~12 min of speech
    assert v.current_settings().target_seconds == 600
    assert "✓" in v.lbl_feasible.text() or "✗" in v.lbl_feasible.text()
    v.combo_target.setCurrentIndex(v.combo_target.count() - 1)   # custom
    v.spin_custom.setValue(2)
    assert v.current_settings().target_seconds == 120
    assert "not realistic" in v.lbl_feasible.text()


# ------------------------------------------------------------------ real render
@pytest.mark.skipif(bool(missing_tools()), reason="say/ffmpeg not available")
def test_generate_video_for_subrange(qapp, tmp_path):
    from src.backend.workers.import_worker import ImportWorker
    out = []
    w = ImportWorker(Path("docs/pdfs/Day1_SAP_BTP_Architecture.pdf").resolve(), "Render", workspace_dir=tmp_path)
    w.finished.connect(out.append)
    w.run()
    proj = out[0]
    for n in proj.narrations:
        n.script = "Short narration for testing."

    report = generate_video(proj, RenderSettings(start=2, end=3, transition_seconds=0.4, name="part"))
    vid = Path(proj.project_dir) / "video" / report["video"]
    assert vid.is_file() and vid.stat().st_size > 1000
    assert report["slide_count"] == 2 and [t["slide"] for t in report["timeline"]] == [2, 3]
    assert (vid.with_suffix(".srt")).read_text().count("-->") == 2

    report2 = generate_video(proj, RenderSettings(start=1, end=1))      # second video, same project
    names = {r["video"] for r in list_generated(proj)}
    assert {report["video"], report2["video"]} <= names
