"""TTS engines, narration audio service, Narration Studio voice UI, and video integration."""
import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.backend.project_manager import ProjectManager
from src.backend.tts import base as tb
from src.backend.tts import service as tts
from src.backend.tts.registry import DEFAULT_ENGINE, engines, get_engine
from src.models.narration import SlideNarration
from src.models.slide import Slide
from src.models.video_config import VideoConfig

KOKORO = get_engine("kokoro-82m")
kokoro_ok = KOKORO.is_installed()[0]
needs_kokoro = pytest.mark.skipif(not kokoro_ok, reason="Kokoro-82M model not installed")


@pytest.fixture
def project(tmp_path):
    pm = ProjectManager(tmp_path)
    proj = pm.create_project("TTS", Path("docs/pdfs/Day1_SAP_BTP_Architecture.pdf").resolve())
    proj.slides = [Slide(slide_id=f"s{i}", slide_number=i, title=f"Slide {i}") for i in (1, 2, 3)]
    proj.narrations = [SlideNarration(slide_id=f"s{i}", slide_number=i, script=f"This is slide {i}. It uses a JWT.")
                       for i in (1, 2, 3)]
    pm.save_project(proj)
    return proj


# ------------------------------------------------------------------ registry / engines
def test_default_engine_is_kokoro():
    assert DEFAULT_ENGINE == "kokoro-82m"
    assert VideoConfig().tts_engine == "kokoro-82m"
    assert get_engine(None).id == "kokoro-82m"
    assert get_engine("piper").id == "kokoro-82m"          # unknown/legacy -> default
    assert {e.id for e in engines()} >= {"kokoro-82m", "macos-say"}


@needs_kokoro
def test_kokoro_speakers_and_capabilities():
    sp = KOKORO.speakers()
    ids = {s.id for s in sp}
    assert {"af_heart", "am_michael", "bf_emma"} <= ids and len(sp) >= 20
    heart = KOKORO.find_speaker("af_heart")
    assert heart.language == "English (US)" and heart.gender == "female voice" and heart.recommended
    assert sp[0].is_english                               # English listed first
    assert KOKORO.capabilities.pauses and not KOKORO.capabilities.emphasis
    assert KOKORO.status().state in (tb.INSTALLED, tb.READY)


def test_missing_model_reports_not_installed(tmp_path):
    from src.backend.tts.kokoro_engine import KokoroEngine
    eng = KokoroEngine(tmp_path / "nowhere")
    st = eng.status()
    assert st.state == tb.NOT_INSTALLED and "Download model" in st.message
    with pytest.raises(RuntimeError):
        eng.load()


# ------------------------------------------------------------------ text preparation
def test_pronunciations_whole_words_only():
    m = {"JWT": "J W T", "CAP": "cap", "mta.yaml": "M T A dot yaml"}
    out = tts.apply_pronunciations("The JWT and JWTs. CAPITAL CAP in mta.yaml", m)
    assert out == "The J W T and JWTs. CAPITAL cap in M T A dot yaml"
    assert tts.clean_text("**bold** `code`") == "bold code"


# ------------------------------------------------------------------ audio generation & staleness
@needs_kokoro
def test_generate_and_outdated_detection(project):
    n1, n2, _ = project.narrations
    assert tts.audio_state(project, n1) == tts.NONE
    tts.generate_slide_audio(project, n1)
    assert tts.audio_state(project, n1) == tts.READY
    assert (Path(project.project_dir) / "audio" / "slide_001.wav").is_file()
    assert n1.audio_duration > 0.5

    from src.backend.narration.narration_manager import NarrationManager
    NarrationManager(project).update_script("s1", "Edited text for slide one.")
    assert tts.audio_state(project, n1) == tts.OUTDATED      # preserved, flagged
    assert n1.audio_path == "audio/slide_001.wav"

    tts.generate_slide_audio(project, n1)                     # explicit regeneration
    assert tts.audio_state(project, n1) == tts.READY

    # Per-slide speaker change only affects that slide
    tts.generate_slide_audio(project, n2)
    project.settings.speaker_mode = "per_slide"
    n1.speaker = "am_michael"
    assert tts.audio_state(project, n1) == tts.OUTDATED
    assert tts.audio_state(project, n2) == tts.READY

    # Global speaker change affects every slide that follows the global voice
    project.settings.speaker_mode = "single"
    project.settings.voice_id = "bf_emma"
    assert tts.audio_state(project, n2) == tts.OUTDATED


@needs_kokoro
def test_sample_and_preview_are_cached(project):
    p1 = tts.sample_audio(project, "af_heart")
    mtime = p1.stat().st_mtime
    assert tts.sample_audio(project, "af_heart") == p1 and p1.stat().st_mtime == mtime
    p2 = tts.preview_audio(project, "Unsaved edited narration text.", "am_michael")
    assert p2.is_file() and p2 != p1


@needs_kokoro
def test_speed_and_pause_change_audio_length(project):
    fast = tts.wav_seconds(tts.synthesize_cached("One. Two. Three. Four.",
                                                 tts.TTSOptions("kokoro-82m", "af_heart", 1.5, 0.1, 0.05),
                                                 tts.cache_dir(project)))
    slow = tts.wav_seconds(tts.synthesize_cached("One. Two. Three. Four.",
                                                 tts.TTSOptions("kokoro-82m", "af_heart", 0.8, 0.8, 0.2),
                                                 tts.cache_dir(project)))
    assert slow > fast


# ------------------------------------------------------------------ Narration Studio UI
def _wait(studio):
    if studio.worker:
        studio.worker.wait(120000)
    for _ in range(20):
        QApplication.processEvents()


@needs_kokoro
def test_narration_studio_voice_workflow(qapp, project, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from src.frontend.narration_studio import NarrationStudio
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    s = NarrationStudio()
    played = []
    monkeypatch.setattr(s.player, "play", lambda path, label="": played.append((Path(path), label)))
    s.load_project(project)

    # model + speakers
    assert s.combo_engine.currentData() == "kokoro-82m"
    assert s.combo_speaker.count() > 5 and s.combo_speaker.currentData() == "af_heart"
    assert "English" in s.lbl_speaker_info.text()
    assert s.spin_sentence.isVisible() or not s.isVisible()   # pause controls exist for Kokoro

    # single mode: changing speaker updates global voice
    i = s.combo_speaker.findData("am_michael")
    s.combo_speaker.setCurrentIndex(i)
    assert project.settings.voice_id == "am_michael"
    assert all(tts.slide_speaker(project, n) == "am_michael" for n in project.narrations)
    assert not s.tabs.isTabEnabled(1)

    # sample + preview (uses unsaved editor text)
    s._play_sample(); _wait(s)
    assert played and played[-1][0].is_file() and "am_michael" in played[-1][1]
    s.script_edit.setText("Changed narration being previewed.")
    s._preview_narration(); _wait(s)
    assert "slide 1" in played[-1][1]

    # per-slide mode: individual assignment does not affect others
    s.radio_per_slide.setChecked(True)
    assert project.settings.speaker_mode == "per_slide" and s.tabs.isTabEnabled(1)
    assert s.assign_table.rowCount() == 3
    combo = s.assign_table.cellWidget(1, 3)
    combo.setCurrentIndex(combo.findData("bf_emma"))
    assert tts.slide_speaker(project, project.narrations[1]) == "bf_emma"
    assert tts.slide_speaker(project, project.narrations[0]) == "am_michael"

    # generate one slide, then all pending
    s._generate("ids", ["s2"]); _wait(s)
    assert tts.audio_state(project, project.narrations[1]) == tts.READY
    assert tts.audio_state(project, project.narrations[0]) == tts.NONE
    s._generate("pending"); _wait(s)
    assert all(tts.audio_state(project, n) == tts.READY for n in project.narrations)
    assert project.narrations[1].audio_meta["speaker"] == "bf_emma"

    # back to single speaker
    s.combo_speaker.setCurrentIndex(s.combo_speaker.findData("af_heart"))  # edits current slide (s1)
    s._apply_speaker_to_all()
    assert project.settings.speaker_mode == "single" and project.settings.voice_id == "af_heart"
    assert all(n.speaker is None for n in project.narrations)

    saved = json.loads((Path(project.project_dir) / "project.json").read_text())
    assert saved["settings"]["voice_id"] == "af_heart"


# ------------------------------------------------------------------ video integration
@needs_kokoro
def test_video_uses_existing_slide_audio_and_tempo(project):
    from src.backend.video.pipeline import generate_video, missing_tools
    from src.backend.video.timing import RenderSettings
    from src.backend.slides.slide_renderer import SlideRenderer
    if missing_tools(project):
        pytest.skip("ffmpeg missing")
    # rendered slide images for 3 slides
    from src.backend.slides.pdf_parser import PDFPresentationParser
    src_pdf = Path(project.project_dir) / project.source_file
    slides, _ = PDFPresentationParser(src_pdf).parse_slides()
    project.slides = slides[:3]
    for s, n in zip(project.slides, project.narrations):
        n.slide_id = s.slide_id
    SlideRenderer(project.project_dir).render_all_slides(pdf_path=src_pdf, slides=project.slides)

    n1 = project.narrations[0]
    tts.generate_slide_audio(project, n1)
    before = (Path(project.project_dir) / n1.audio_path).stat().st_mtime
    report = generate_video(project, RenderSettings(start=1, end=3, speed=1.25, allow_speed_adjust=False))
    assert (Path(project.project_dir) / n1.audio_path).stat().st_mtime == before   # reused, not regenerated
    assert all(tts.audio_state(project, n) == tts.READY for n in project.narrations)  # missing ones generated
    assert report["speed_used"] == 1.25
    assert report["timeline"][0]["narration"] == pytest.approx(n1.audio_duration / 1.25, abs=0.01)
    assert report["tts_engine"] == "kokoro-82m"
