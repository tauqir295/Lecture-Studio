"""Slide transitions: registry, settings resolution, timing, rendering, preview and Video Studio UI."""
import re
import subprocess
from pathlib import Path

import pytest

from src.backend.video import transitions as tx
from src.backend.video.pipeline import (build_srt, ffmpeg_path, generate_video, missing_tools, quantize_plan,
                                        transition_cmd, transition_preview_frames, _VENC)
from src.backend.video.timing import RenderSettings, plan_timing
from src.models.narration import SlideNarration
from src.models.project import Project
from src.models.slide import Slide
from src.models.video_config import VideoConfig

REQUIRED = ["none", "fade", "crossfade", "slide_left", "slide_right", "slide_up", "slide_down",
            "wipe_left", "wipe_right", "wipe_up", "wipe_down", "zoom_in", "zoom_out"]
needs_ffmpeg = pytest.mark.skipif(ffmpeg_path() is None, reason="ffmpeg not available")


# ------------------------------------------------------------------ registry / settings
def test_registry_has_required_effects_and_is_extensible():
    keys = [t.key for t in tx.types()]
    assert set(REQUIRED) <= set(keys)
    tx.register("test_fx", "Test FX", lambda a, b, d, n, w, h: f"[{a}][{b}]xfade=transition=radial:duration={d}[v]")
    try:
        assert tx.label("test_fx") == "Test FX"
        assert "radial" in tx.filter_graph("test_fx", 0.5, 15, 320, 180)
    finally:
        tx._REGISTRY.pop("test_fx")
    assert tx.DURATIONS == [0.25, 0.5, 0.75, 1.0, 1.5, 2.0]


def test_resolve_default_override_and_none():
    vc = VideoConfig(transition="wipe_left", transition_duration=0.75,
                     slide_transitions={"b": {"type": "zoom_in", "duration": 1.5},
                                        "c": {"type": "none", "duration": 0.0},
                                        "d": {"type": "bogus"}})
    assert tx.resolve(vc, "a") == ("wipe_left", 0.75)
    assert tx.resolve(vc, "b") == ("zoom_in", 1.5)
    assert tx.resolve(vc, "c") == ("none", 0.0)
    assert tx.resolve(vc, "d") == ("none", 0.0)       # unknown effect degrades to a cut
    inc = tx.incoming(vc, ["b", "a", "c"])
    assert inc == {"b": ("none", 0.0), "a": ("wipe_left", 0.75), "c": ("none", 0.0)}   # range starts on b


def test_transition_settings_saved_with_project(tmp_path):
    from src.backend.project_manager import ProjectManager
    pm = ProjectManager(tmp_path)
    proj = Project(project_id="p", project_name="P", project_dir=str(tmp_path))
    proj.settings.transition = "slide_up"
    proj.settings.slide_transitions = {"s2": {"type": "zoom_out", "duration": 2.0}}
    pm.save_project(proj)
    again = pm.load_project(tmp_path)
    assert again.settings.transition == "slide_up"
    assert again.settings.slide_transitions == {"s2": {"type": "zoom_out", "duration": 2.0}}


# ------------------------------------------------------------------ timing / subtitles
def _deck(n, words="word " * 150):
    slides = [Slide(slide_id=f"s{i}", slide_number=i, title=f"T{i}") for i in range(1, n + 1)]
    narr = [SlideNarration(slide_id=f"s{i}", slide_number=i, script=words) for i in range(1, n + 1)]
    return slides, narr


def test_transitions_add_to_duration_and_delay_subtitles():
    slides, narr = _deck(4)
    vc = VideoConfig(transition="crossfade", transition_duration=1.0,
                     slide_transitions={"s3": {"type": "none"}, "s4": {"type": "zoom_in", "duration": 2.0}})
    cfg = RenderSettings(start=1, end=4, base_wpm=150, reading_seconds=1.0, min_slide_seconds=0)
    plan = plan_timing(slides, narr, cfg, transitions=tx.incoming(vc, [s.slide_id for s in slides]))
    assert [t.transition_seconds for t in plan.slides] == [0.0, 1.0, 0.0, 2.0]
    assert [t.transition_type for t in plan.slides] == ["none", "crossfade", "none", "zoom_in"]
    assert plan.total_seconds == pytest.approx(4 * 61 + 3.0)
    assert plan.narration_seconds == pytest.approx(240)              # narration untouched

    srt = build_srt(plan, {n.slide_id: "One. Two." for n in narr})
    starts = re.findall(r"(\d\d:\d\d:\d\d,\d\d\d) -->", srt)
    assert starts[0] == "00:00:00,000"                                # first slide: no transition
    assert starts[2] == "00:01:02,000"                                # 61 s slide 1 + 1 s transition


def test_target_fitting_accounts_for_transitions():
    slides, narr = _deck(10)
    vc = VideoConfig(transition="fade", transition_duration=2.0)
    cfg = RenderSettings(start=1, end=10, base_wpm=150, target_seconds=700, min_slide_seconds=0, reading_seconds=1)
    plan = plan_timing(slides, narr, cfg, transitions=tx.incoming(vc, [s.slide_id for s in slides]))
    assert plan.feasible and plan.total_seconds == pytest.approx(700, abs=0.5)


def test_quantize_plan_is_frame_exact_and_never_shortens():
    slides, narr = _deck(3, words="word " * 37)
    plan = plan_timing(slides, narr, RenderSettings(start=1, end=3, transition_seconds=0.33, reading_seconds=0.21))
    q = quantize_plan(plan, 30)
    for a, b in zip(plan.slides, q.slides):
        assert b.narration_seconds == a.narration_seconds
        assert b.hold_seconds >= a.hold_seconds - 1e-9
        assert (b.narration_seconds + b.hold_seconds) * 30 == pytest.approx(round((b.narration_seconds + b.hold_seconds) * 30), abs=1e-4)
        assert b.transition_seconds * 30 == pytest.approx(round(b.transition_seconds * 30))


# ------------------------------------------------------------------ rendering
def _images(tmp_path: Path, n: int = 3):
    ff = ffmpeg_path()
    colors = ["red", "blue", "green", "white", "yellow"]
    paths = []
    for i in range(n):
        p = tmp_path / "slides" / f"slide_{i + 1:03d}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color={colors[i % 5]}:s=320x180",
                        "-frames:v", "1", str(p)], check=True)
        paths.append(p)
    return paths


def _duration(ff: str, path: Path) -> float:
    err = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


@needs_ffmpeg
@pytest.mark.parametrize("key", [k for k in REQUIRED if k != "none"] + ["dissolve"])
def test_every_effect_renders(tmp_path, key):
    a, b = _images(tmp_path, 2)
    out = tmp_path / f"{key}.mp4"
    cmd = transition_cmd(ffmpeg_path(), a, b, key, 0.5, 12, 320, 180, 24) + _VENC + [str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert _duration(ffmpeg_path(), out) == pytest.approx(0.5, abs=0.05)


def _image_project(tmp_path, n=3) -> Project:
    imgs = _images(tmp_path, n)
    proj = Project(project_id="tp", project_name="T", project_dir=str(tmp_path))
    proj.settings = VideoConfig(width=320, height=180, resolution="320x180", fps=24)
    proj.slides = [Slide(slide_id=f"s{i}", slide_number=i, title=f"T{i}",
                         image_path=str(imgs[i - 1].relative_to(tmp_path))) for i in range(1, n + 1)]
    proj.narrations = [SlideNarration(slide_id=f"s{i}", slide_number=i, script="") for i in range(1, n + 1)]
    return proj


@needs_ffmpeg
def test_preview_frames_show_from_and_to(tmp_path):
    proj = _image_project(tmp_path, 2)
    frames, w, h, fps = transition_preview_frames(proj, "s1", "s2", "slide_left", 0.5, width=160, hold=0.25)
    assert (w, h) == (160, 90) and fps == 24
    assert len(frames) == 6 + 12 + 6
    assert all(len(f) == w * h * 3 for f in frames)
    assert frames[0][:3] != frames[-1][:3]                     # red -> blue
    cut, *_ = transition_preview_frames(proj, "s1", "s2", "none", 1.0, width=160, hold=0.25)
    assert len(cut) == 12


@needs_ffmpeg
@pytest.mark.skipif(bool(missing_tools()), reason="tools not available")
def test_generate_video_with_mixed_transitions(tmp_path):
    proj = _image_project(tmp_path, 3)
    proj.settings.transition, proj.settings.transition_duration = "zoom_out", 1.0
    proj.settings.slide_transitions = {"s3": {"type": "wipe_up", "duration": 0.5}}
    cfg = RenderSettings(start=1, end=3, min_slide_seconds=1.0, reading_seconds=0.0)
    report = generate_video(proj, cfg)
    mp4 = tmp_path / "video" / report["video"]
    assert [t["transition_type"] for t in report["timeline"]] == ["none", "zoom_out", "wipe_up"]
    assert report["total_seconds"] == pytest.approx(3 * 1.0 + 1.0 + 0.5, abs=0.01)
    assert _duration(ffmpeg_path(), mp4) == pytest.approx(report["total_seconds"], abs=0.1)
    assert report["transitions"]["per_slide"] == proj.settings.slide_transitions


# ------------------------------------------------------------------ Video Studio UI
def test_video_studio_transition_controls(qapp, tmp_path):
    from src.frontend.video_studio import VideoStudio
    proj = Project(project_id="ui", project_name="UI", project_dir=str(tmp_path))
    proj.slides, proj.narrations = _deck(5)
    v = VideoStudio()
    v.load_project(proj)
    assert v.trans_table.rowCount() == 5

    base = v.plan.total_seconds
    v._set_combo(v.combo_trans_default, "slide_right")
    v._set_combo(v.combo_trans_default_dur, 2.0)
    assert proj.settings.transition == "slide_right" and proj.settings.transition_duration == 2.0
    assert v.plan.total_seconds == pytest.approx(base + 4 * (2.0 - 0.5))

    v.trans_table.selectRow(2)
    v._set_combo(v.combo_trans_sel, "zoom_in"); v._set_combo(v.combo_trans_sel_dur, 0.25)
    v._apply_transition_selected()
    assert proj.settings.slide_transitions == {"s3": {"type": "zoom_in", "duration": 0.25}}
    v._no_transition_selected()
    assert tx.resolve(proj.settings, "s3") == ("none", 0.0)
    assert "start of video" in v.timeline_table.item(0, 3).text()

    v.trans_table.selectAll()
    v._vary_transition_selected()
    assert len({o["type"] for o in proj.settings.slide_transitions.values()}) == 5

    v.chk_trans_override.setChecked(True)
    v._apply_transition_all()
    assert proj.settings.slide_transitions == {}
    from src.backend.project_manager import ProjectManager
    saved = ProjectManager(tmp_path).load_project(tmp_path).settings
    assert (saved.transition, saved.transition_duration, saved.slide_transitions) == ("slide_right", 2.0, {})


# ------------------------------------------------------------------ cross-platform helpers
def test_models_root_env_and_user_dir(monkeypatch, tmp_path):
    from src.backend.tts import registry
    monkeypatch.setenv("LECTURE_STUDIO_MODELS", str(tmp_path))
    assert registry.models_root() == tmp_path
    for plat, part in (("win32", "LectureStudio"), ("darwin", "Application Support"), ("linux", "lecture-studio")):
        monkeypatch.setattr(registry.sys, "platform", plat)
        assert part in str(registry.user_models_dir())


def test_concat_list_handles_quotes_and_spaces(tmp_path):
    from src.backend.video.pipeline import _concat
    ff = ffmpeg_path()
    if not ff:
        pytest.skip("ffmpeg not available")
    d = tmp_path / "it's a dir"
    d.mkdir()
    a, b = _images(d, 2)
    clips = []
    for i, img in enumerate((a, b)):
        c = d / f"c{i}.mp4"
        subprocess.run([ff, "-y", "-loglevel", "error", "-loop", "1", "-framerate", "24", "-i", str(img),
                        "-frames:v", "12"] + _VENC + [str(c)], check=True)
        clips.append(c)
    out = d / "joined.mp4"
    _concat(ff, clips, d / "list.txt", out)
    assert _duration(ff, out) == pytest.approx(1.0, abs=0.05)
