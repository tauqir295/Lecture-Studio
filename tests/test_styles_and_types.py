"""Delivery styles (emotional narration) and video types (frame, layout, overlay, pacing presets)."""
import hashlib
import json
import re
import subprocess
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from src.backend.tts import emotion
from src.backend.tts import service as tts
from src.backend.tts.base import Capabilities, Speaker, TTSEngine
from src.backend.video import transitions as tx
from src.backend.video import video_types as vt
from src.backend.video.pipeline import body_graph, ffmpeg_path, generate_video, layout_preview_frame, missing_tools
from src.backend.video.timing import RenderSettings
from src.models.narration import SlideNarration
from src.models.project import Project
from src.models.slide import Slide
from src.models.video_config import VideoConfig

needs_ffmpeg = pytest.mark.skipif(ffmpeg_path() is None, reason="ffmpeg not available")


class FakeEngine(TTSEngine):
    id, name = "fake", "Fake TTS"

    def __init__(self, caps):
        super().__init__()
        self.capabilities = caps
        self.calls = []

    def is_installed(self):
        return True, ""

    def speakers(self):
        return [Speaker("v1", "Voice 1", "English (US)")]

    def _synthesize(self, text, speaker, speed, sentence_pause, clause_pause):
        self.calls.append(dict(speed=speed, sp=sentence_pause, cp=clause_pause,
                               expr=self._expressiveness, style=self._style))
        return np.zeros(2400, dtype=np.float32), 24000


KOKORO_LIKE = Capabilities(pauses=True)
PIPER_LIKE = Capabilities(pauses=False, expressiveness=True)
NATIVE = Capabilities(pauses=True, styles=("calm", "dramatic"))


# ------------------------------------------------------------------ styles
def test_required_styles_exist():
    keys = {s.key for s in emotion.styles()}
    assert {"neutral", "friendly", "enthusiastic", "calm", "serious", "storytelling", "dramatic",
            "inspirational"} <= keys


def test_apply_uses_only_supported_controls():
    k = emotion.apply("dramatic", FakeEngine(KOKORO_LIKE), 1.0, 0.3, 0.1)
    assert k.speed == pytest.approx(0.88) and k.sentence_pause == pytest.approx(0.45)
    assert k.expressiveness == 1.0 and k.native_style == ""                    # no expressiveness control
    p = emotion.apply("dramatic", FakeEngine(PIPER_LIKE), 1.0, 0.3, 0.1)
    assert p.sentence_pause == 0.0 and p.expressiveness == pytest.approx(1.3)  # no pause control
    n = emotion.apply("calm", FakeEngine(NATIVE), 1.0, 0.3, 0.1)
    assert n.native_style == "calm" and n.speed == 1.0                         # model performs it itself
    assert emotion.apply("enthusiastic", FakeEngine(Capabilities(speed_range=(0.5, 1.05))), 1.0, 0, 0).speed == 1.05
    assert emotion.apply("unknown-style", FakeEngine(KOKORO_LIKE), 1.0, 0.3, 0.1) == \
        emotion.apply("neutral", FakeEngine(KOKORO_LIKE), 1.0, 0.3, 0.1)


def test_controls_and_description_match_engine():
    assert emotion.controls_for(FakeEngine(KOKORO_LIKE)) == ["pace", "pauses"]
    assert emotion.controls_for(FakeEngine(PIPER_LIKE)) == ["pace", "expressiveness"]
    assert emotion.controls_for(FakeEngine(NATIVE))[0] == "native"
    assert "no emotion input" in emotion.describe_support(FakeEngine(KOKORO_LIKE))
    assert "intonation" in emotion.describe_support(FakeEngine(PIPER_LIKE))


def test_engine_receives_style_parameters(monkeypatch, tmp_path):
    eng = FakeEngine(PIPER_LIKE)
    monkeypatch.setattr(tts, "get_engine", lambda _id=None: eng)
    tts.synthesize_cached("Hello.", tts.TTSOptions("fake", "v1", 1.0, 0, 0, "enthusiastic"), tmp_path)
    assert eng.calls[-1]["speed"] == pytest.approx(1.10) and eng.calls[-1]["expr"] == pytest.approx(1.3)
    assert eng._expressiveness == 1.0                                          # reset after the call
    neng = FakeEngine(NATIVE)
    monkeypatch.setattr(tts, "get_engine", lambda _id=None: neng)
    tts.synthesize_cached("Hello.", tts.TTSOptions("fake", "v1", 1.0, 0.3, 0.1, "dramatic"), tmp_path / "n")
    assert neng.calls[-1]["style"] == "dramatic"


def test_neutral_keeps_existing_audio_valid():
    o = tts.TTSOptions("kokoro-82m", "af_heart", 1.0, 0.3, 0.1)
    legacy = {"engine": "kokoro-82m", "speaker": "af_heart", "speed": 1.0, "sentence_pause": 0.3, "clause_pause": 0.1}
    assert o.as_dict() == legacy                                               # same metadata as before styles
    assert o.key("x") == hashlib.sha1(json.dumps({**legacy, "text": "x"}, sort_keys=True).encode()).hexdigest()[:20]
    assert "emotion" in tts.TTSOptions("kokoro-82m", "af_heart", emotion="calm").as_dict()


def test_per_slide_style_overrides_project_and_marks_audio_outdated(tmp_path):
    proj = Project(project_id="p", project_name="P", project_dir=str(tmp_path))
    proj.settings.emotion = "calm"
    a = SlideNarration(slide_id="s1", slide_number=1, script="Hi.")
    b = SlideNarration(slide_id="s2", slide_number=2, script="Hi.", emotion="dramatic")
    assert tts.options_for(proj, a).emotion == "calm" and tts.options_for(proj, b).emotion == "dramatic"
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "slide_001.wav").write_bytes(b"x" * 100)
    a.audio_path, a.audio_meta = "audio/slide_001.wav", tts._meta(proj, a)
    assert tts.audio_state(proj, a) == tts.READY
    a.emotion = "enthusiastic"
    assert tts.audio_state(proj, a) == tts.OUTDATED
    assert SlideNarration.from_dict(b.to_dict()).emotion == "dramatic"


# ------------------------------------------------------------------ video types
def test_video_types_are_consistent():
    keys = {t.key for t in vt.types()}
    assert {"tutorial", "explainer", "storytelling", "software", "news", "training", "promo", "short",
            "podcast", "photo"} <= keys
    styles = {s.key for s in emotion.styles()}
    for t in vt.types():
        assert t.aspect in vt.ASPECTS and t.layout in vt.LAYOUTS and t.overlay in vt.OVERLAYS
        assert t.transition in {x.key for x in tx.types()} and t.emotion in styles
    assert vt.get("short").aspect == "9:16" and vt.get("podcast").overlay == "waveform"


def test_apply_type_sets_defaults_and_keeps_per_slide_choices():
    vc = VideoConfig(slide_transitions={"s2": {"type": "wipe_up", "duration": 1.0}})
    vt.apply_to_config(vc, "short")
    assert (vc.width, vc.height, vc.aspect_ratio, vc.layout, vc.overlay) == (1080, 1920, "9:16", "fill_blur", "progress")
    assert vc.transition == "slide_up" and vc.emotion == "enthusiastic" and vc.video_type == "short"
    assert vc.slide_transitions == {"s2": {"type": "wipe_up", "duration": 1.0}}
    vt.apply_to_config(vc, "tutorial")
    assert (vc.width, vc.height, vc.layout, vc.overlay) == (1920, 1080, "fit", "none")
    assert VideoConfig.from_dict(vc.to_dict()).video_type == "tutorial"


def test_body_graph_variants():
    assert "zoompan" in body_graph("ken_burns", "none", 640, 360, 24, 48, 0, 10)
    assert "drawbox" in body_graph("fill_blur", "progress", 640, 360, 24, 48, 2.0, 10)
    assert "showwaves" in body_graph("fit", "waveform", 640, 360, 24, 48, 0, 10)
    assert body_graph("fit", "none", 640, 360, 24, 48, 0, 10).endswith("[v]")


# ------------------------------------------------------------------ rendering
def _project(tmp_path, n=3) -> Project:
    ff = ffmpeg_path()
    (tmp_path / "slides").mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360", "-frames:v", "1",
                        str(tmp_path / "slides" / f"s{i}.png")], check=True)
    p = Project(project_id="vt", project_name="VT", project_dir=str(tmp_path))
    p.slides = [Slide(slide_id=f"s{i}", slide_number=i, title=f"T{i}", image_path=f"slides/s{i}.png")
                for i in range(1, n + 1)]
    p.narrations = [SlideNarration(slide_id=f"s{i}", slide_number=i, script="") for i in range(1, n + 1)]
    return p


def _duration(path: Path) -> float:
    err = subprocess.run([ffmpeg_path(), "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


@needs_ffmpeg
@pytest.mark.skipif(bool(missing_tools()), reason="tools not available")
@pytest.mark.parametrize("vtype", ["tutorial", "news", "short", "podcast", "storytelling"])
def test_each_type_renders_with_exact_timing(tmp_path, vtype):
    p = _project(tmp_path)
    vt.apply_to_config(p.settings, vtype)
    p.settings.width //= 4; p.settings.height //= 4; p.settings.fps = 24          # small and fast
    r = generate_video(p, RenderSettings(start=1, end=3, min_slide_seconds=1.0, reading_seconds=0.0))
    mp4 = tmp_path / "video" / r["video"]
    assert r["video_type"] == vtype and r["frame"] == f"{p.settings.width}x{p.settings.height}"
    assert _duration(mp4) == pytest.approx(r["total_seconds"], abs=0.05)


@needs_ffmpeg
def test_layout_preview_frame_has_frame_shape(tmp_path):
    p = _project(tmp_path, 1)
    vt.apply_to_config(p.settings, "short")
    data, w, h = layout_preview_frame(p, "s1", 270)
    assert (w, h) == (270, 480) and len(data) == w * h * 3


# ------------------------------------------------------------------ UI
def test_video_studio_type_panel(qapp, tmp_path):
    from src.frontend.video_studio import VideoStudio
    proj = Project(project_id="ui", project_name="UI", project_dir=str(tmp_path))
    proj.slides = [Slide(slide_id=f"s{i}", slide_number=i, title=f"T{i}") for i in (1, 2, 3)]
    proj.narrations = [SlideNarration(slide_id=f"s{i}", slide_number=i, script="word " * 30) for i in (1, 2, 3)]
    v = VideoStudio()
    v.load_project(proj)
    assert v.combo_type.currentData() == "tutorial"
    v.combo_type.setCurrentIndex(v.combo_type.findData("podcast"))
    vc = proj.settings
    assert (vc.video_type, vc.overlay, vc.transition, vc.emotion) == ("podcast", "waveform", "crossfade", "friendly")
    assert v.combo_overlay.currentData() == "waveform" and v.combo_trans_default.currentData() == "crossfade"
    assert v.spin_reading.value() == pytest.approx(0.8)
    v.combo_aspect.setCurrentIndex(v.combo_aspect.findData("1:1"))
    assert (vc.width, vc.height) == (1080, 1080)
    from src.backend.project_manager import ProjectManager
    saved = ProjectManager(tmp_path).load_project(tmp_path).settings
    assert (saved.video_type, saved.aspect_ratio, saved.overlay) == ("podcast", "1:1", "waveform")


def test_narration_studio_style_controls(qapp, tmp_path):
    from src.frontend.narration_studio import NarrationStudio
    proj = Project(project_id="ns", project_name="NS", project_dir=str(tmp_path))
    proj.slides = [Slide(slide_id="s1", slide_number=1, title="A"), Slide(slide_id="s2", slide_number=2, title="B")]
    proj.narrations = [SlideNarration(slide_id=f"s{i}", slide_number=i, script="Hello there.") for i in (1, 2)]
    ns = NarrationStudio()
    ns.load_project(proj)
    assert ns.lbl_style_support.text()                                     # explains what styles change
    ns.combo_style.setCurrentIndex(ns.combo_style.findData("calm"))
    assert proj.settings.emotion == "calm"
    ns.script_list.setCurrentRow(1)
    ns.combo_slide_style.setCurrentIndex(ns.combo_slide_style.findData("dramatic"))
    assert proj.narrations[1].emotion == "dramatic" and proj.narrations[0].emotion is None
    ns.script_list.setCurrentRow(0)
    assert ns.combo_slide_style.currentData() is None                       # shows "Project style"
    ns.script_list.setCurrentRow(1)
    assert ns.combo_slide_style.currentData() == "dramatic"
