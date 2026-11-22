"""Tests for Qwen3-TTS engine, model manager integration, downloading, offline inference,
emotion instruction control, storage management, and UI workflows.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from src.backend.audio.script import parse
from src.backend.project_manager import ProjectManager
from src.backend.tts import base as tb
from src.backend.tts import emotion, registry
from src.backend.tts import service as tts
from src.backend.tts.qwen3_engine import (
    Qwen3TTSEngine,
    sanitize_text_and_extract_tags,
    translate_emotion_to_instruction,
)
from src.backend.tts.qwen3_manager import (
    MODEL_SPECS,
    TOKENIZER_SPEC,
    Qwen3Manager,
    format_bytes,
)
from src.frontend.model_manager import ModelManagerDialog, Qwen3SettingsDialog
from src.models.narration import SlideNarration
from src.models.slide import Slide


@pytest.fixture
def tts_env(tmp_path, monkeypatch):
    """Isolated models environment for Qwen3 and custom models."""
    models_dir = tmp_path / "models"
    tts_root = models_dir / "tts"
    tts_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LECTURE_STUDIO_MODELS", str(models_dir))
    monkeypatch.setenv("LECTURE_STUDIO_CUSTOM_MODELS", str(tts_root / "custom"))
    registry.reset()
    yield tts_root
    registry.reset()


@pytest.fixture
def installed_qwen3(tts_env):
    """Installs mock 0.6B CustomVoice and 1.7B VoiceDesign models for fast testing."""
    mgr = Qwen3Manager(tts_env)
    mgr.download_model("qwen3-tts-0.6b-customvoice")
    mgr.download_model("qwen3-tts-1.7b-voicedesign")
    registry.reload()
    return mgr


# ================================================================== 1. Registration & Specs
def test_qwen3_engines_registered_in_registry(tts_env):
    engines = {e.id: e for e in registry.engines()}
    for mid in ("qwen3-tts-0.6b-customvoice", "qwen3-tts-1.7b-customvoice", "qwen3-tts-1.7b-voicedesign"):
        assert mid in engines, f"Engine {mid} not registered"
        eng = engines[mid]
        assert isinstance(eng, Qwen3TTSEngine)
        assert eng.downloadable is True
        assert eng.capabilities.instructions is True
        assert eng.capabilities.pronunciation is True
        assert eng.sample_rate == 24000
        assert len(eng.capabilities.styles) >= 15


def test_qwen3_speakers_customvoice(installed_qwen3):
    eng = registry.get_engine("qwen3-tts-0.6b-customvoice")
    sp = eng.speakers()
    speaker_ids = {s.id for s in sp}
    # Check that standard 9 timbres exist
    expected = {"Vivian", "Serena", "Uncle_Fu", "Aiden", "Dylan", "Eric", "Ono_Anna", "Ryan", "Sohee"}
    assert expected <= speaker_ids

    # Check Serena and Aiden recommended
    serena = eng.find_speaker("Serena")
    assert serena is not None and serena.recommended is True and serena.is_english is True
    aiden = eng.find_speaker("Aiden")
    assert aiden is not None and aiden.recommended is True and aiden.is_english is True

    # English voices listed first
    assert sp[0].is_english is True
    assert eng.default_speaker() == "Serena"


def test_qwen3_speakers_voicedesign(installed_qwen3):
    eng = registry.get_engine("qwen3-tts-1.7b-voicedesign")
    assert eng.capabilities.voice_design is True
    sp = eng.speakers()
    assert len(sp) >= 5
    ids = {s.id for s in sp}
    assert "voice_design_female_academic" in ids
    assert "voice_design_male_authoritative" in ids
    assert "voice_design_custom" in ids
    assert eng.default_speaker() == "voice_design_female_academic"


# ================================================================== 2. Download, Tokenizer, Verification
def test_download_model_and_tokenizer(tts_env):
    mgr = Qwen3Manager(tts_env)
    progress_records = []

    def on_progress(pct: int, msg: str):
        progress_records.append((pct, msg))

    # Download 0.6B CustomVoice (should download tokenizer first automatically)
    assert not mgr.is_tokenizer_installed()[0]
    assert not mgr.is_model_installed("qwen3-tts-0.6b-customvoice")[0]

    mgr.download_model("qwen3-tts-0.6b-customvoice", progress=on_progress)

    assert mgr.is_tokenizer_installed()[0]
    assert mgr.is_model_installed("qwen3-tts-0.6b-customvoice")[0]
    assert progress_records[-1][0] == 100

    # Check files exist
    tok_dir = mgr.tokenizer_dir()
    for f in TOKENIZER_SPEC["required_files"]:
        assert (tok_dir / f).is_file()

    model_dir = mgr.model_dir("qwen3-tts-0.6b-customvoice")
    for f in MODEL_SPECS["qwen3-tts-0.6b-customvoice"].required_files:
        assert (model_dir / f).is_file()
    assert (model_dir / "manifest.json").is_file()


def test_download_cancellation(tts_env):
    mgr = Qwen3Manager(tts_env)
    steps = 0

    def cancel_after_two_steps():
        nonlocal steps
        steps += 1
        return steps >= 2

    with pytest.raises(RuntimeError, match="Download cancelled"):
        mgr.download_model("qwen3-tts-0.6b-customvoice", cancel=cancel_after_two_steps)

    # Partial files should have been cleaned up
    mdir = mgr.model_dir("qwen3-tts-0.6b-customvoice")
    assert not list(mdir.glob("*.part"))


def test_model_verification(installed_qwen3, tts_env):
    mgr = installed_qwen3
    eng = registry.get_engine("qwen3-tts-0.6b-customvoice")

    ok, msg = eng.verify()
    assert ok is True and "verified" in msg.lower()

    # Corrupt model by removing a file
    model_dir = mgr.model_dir("qwen3-tts-0.6b-customvoice")
    (model_dir / "model.safetensors").unlink()

    ok, msg = eng.verify()
    assert ok is False and "missing" in msg.lower()


# ================================================================== 3. Emotion & Instruction Translation
def test_translate_emotion_tags_to_instructions():
    tags = ["happy", "sad", "excited", "angry", "whispering", "calm"]
    for tag in tags:
        inst = translate_emotion_to_instruction(tag)
        assert len(inst) > 10
        assert inst != translate_emotion_to_instruction("neutral")

    # Happy instruction contains bright/cheerful/happy
    assert any(w in translate_emotion_to_instruction("happy").lower() for w in ("happy", "cheerful", "bright"))
    # Whispering contains whisper
    assert "whisper" in translate_emotion_to_instruction("whispering").lower()
    # Calm contains calm / soothing
    assert any(w in translate_emotion_to_instruction("calm").lower() for w in ("calm", "soothing", "peaceful"))

    # Custom instruction appended
    combined = translate_emotion_to_instruction("happy", "Speak like a professor")
    assert "Speak like a professor" in combined


def test_inline_emotion_tag_sanitization():
    raw = "Good morning! [happy] We are delighted to begin today's lecture. [pause 1.5s] [whispering] Pay close attention."
    clean, tag, pause = sanitize_text_and_extract_tags(raw)

    # Tags must NOT appear in spoken text
    assert "[happy]" not in clean
    assert "[whispering]" not in clean
    assert "[pause 1.5s]" not in clean
    assert "delighted to begin" in clean
    assert "Pay close attention" in clean
    assert pause >= 1.5
    assert tag in ("happy", "whispering")


def test_bracketed_non_tags_preserved():
    text = "Refer to formula [1] and algorithm [fig-2]."
    clean, tag, _ = sanitize_text_and_extract_tags(text)
    assert "[1]" in clean
    assert "[fig-2]" in clean
    assert tag is None


# ================================================================== 4. Offline Inference
def test_qwen3_offline_inference_customvoice(installed_qwen3):
    eng = registry.get_engine("qwen3-tts-0.6b-customvoice")
    text = "In this lecture, we explore cloud application architecture step by step."

    audio, sr = eng.synthesize(text, speaker="Serena", speed=1.0, style="calm")
    assert sr == 24000
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert len(audio) > sr * 1.5
    assert float(np.abs(audio).max()) > 0.05


def test_qwen3_offline_inference_voicedesign(installed_qwen3):
    eng = registry.get_engine("qwen3-tts-1.7b-voicedesign")
    text = "Welcome to zero shot voice design with natural language instructions."

    audio, sr = eng.synthesize(text, speaker="voice_design_female_academic", speed=1.0, style="inspirational")
    assert sr == 24000
    assert len(audio) > sr * 1.0
    assert float(np.abs(audio).max()) > 0.05


def test_speed_and_pause_affect_audio_length(installed_qwen3):
    eng = registry.get_engine("qwen3-tts-0.6b-customvoice")
    text = "First concept. Second concept."

    fast_audio, _ = eng.synthesize(text, speaker="Aiden", speed=1.8, sentence_pause=0.0)
    slow_audio, _ = eng.synthesize(text, speaker="Aiden", speed=0.7, sentence_pause=1.0)

    assert len(slow_audio) > len(fast_audio)


def test_audio_studio_integration_with_qwen3(installed_qwen3, tmp_path):
    from src.backend.audio.studio import AudioDocument, AudioSettings, synthesize_segment
    from src.models.project import Project

    script_text = "[excited] Welcome to Lecture Studio! [pause 1s] [whispering] Here is an important note."
    doc = AudioDocument(
        doc_id="test-doc",
        name="Test Doc",
        text=script_text,
        settings=AudioSettings(engine="qwen3-tts-0.6b-customvoice", speaker="Serena"),
        folder=str(tmp_path / "audio_doc"),
    )
    segments = doc.parsed().segments
    assert len(segments) >= 2
    assert segments[0].emotion == "excited"

    # Synthesize segment using Qwen3
    seg_wav = synthesize_segment(doc, segments[0])
    assert seg_wav.is_file() and seg_wav.stat().st_size > 44


# ================================================================== 5. Storage Management & Settings
def test_storage_usage_calculation(installed_qwen3, tts_env):
    mgr = installed_qwen3
    u_tok = mgr.tokenizer_disk_usage()
    u_06b = mgr.disk_usage("qwen3-tts-0.6b-customvoice")
    u_tot = mgr.total_disk_usage()

    assert u_tok > 0
    assert u_06b > 0
    assert u_tot >= u_tok + u_06b
    assert "KB" in format_bytes(1024) or "B" in format_bytes(1024)


def test_remove_model_and_storage_update(installed_qwen3, tts_env):
    mgr = installed_qwen3
    eng = registry.get_engine("qwen3-tts-0.6b-customvoice")
    assert eng.is_installed()[0] is True

    # Remove 0.6B model
    eng.remove()
    assert eng.is_installed()[0] is False
    assert mgr.disk_usage("qwen3-tts-0.6b-customvoice") == 0


def test_model_settings_persistence(installed_qwen3):
    mgr = installed_qwen3
    mid = "qwen3-tts-0.6b-customvoice"
    settings = mgr.load_settings(mid)
    settings["custom_instruction"] = "Always speak calmly."
    settings["speaking_rate"] = 1.25
    mgr.save_settings(mid, settings)

    loaded = mgr.load_settings(mid)
    assert loaded["custom_instruction"] == "Always speak calmly."
    assert loaded["speaking_rate"] == 1.25


# ================================================================== 6. Narration Studio & Switching
def test_narration_studio_model_switching(qapp, installed_qwen3, tmp_path, monkeypatch):
    from src.frontend.narration_studio import NarrationStudio
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    pm = ProjectManager(tmp_path)
    proj = pm.create_project("SwitchTest", Path("docs/pdfs/Day1_SAP_BTP_Architecture.pdf").resolve())
    proj.slides = [Slide(slide_id="s1", slide_number=1, title="Intro")]
    proj.narrations = [SlideNarration(slide_id="s1", slide_number=1, script="Welcome to this tutorial.")]
    pm.save_project(proj)

    studio = NarrationStudio()
    studio.load_project(proj)

    # Select Qwen3-TTS 0.6B CustomVoice
    studio.select_engine("qwen3-tts-0.6b-customvoice")
    assert proj.settings.tts_engine == "qwen3-tts-0.6b-customvoice"
    assert "qwen3" in studio.combo_engine.currentData().lower()
    assert studio.combo_speaker.count() >= 5
    assert studio.combo_speaker.findData("Serena") >= 0
    assert "instruction-based" in studio.lbl_style_support.text()

    # Previews work
    prev_wav = tts.preview_audio(proj, "Testing preview.", speaker="Serena")
    assert prev_wav.is_file() and prev_wav.stat().st_size > 44

    # Switch back to Kokoro-82M
    studio.select_engine("kokoro-82m")
    assert proj.settings.tts_engine == "kokoro-82m"


def test_fallback_when_selected_qwen3_removed(qapp, installed_qwen3, tmp_path):
    from src.frontend.narration_studio import NarrationStudio
    pm = ProjectManager(tmp_path)
    proj = pm.create_project("FallbackTest", Path("docs/pdfs/Day1_SAP_BTP_Architecture.pdf").resolve())
    proj.settings.tts_engine = "qwen3-tts-0.6b-customvoice"
    proj.settings.voice_id = "Serena"
    pm.save_project(proj)

    # Remove the model
    installed_qwen3.remove_model("qwen3-tts-0.6b-customvoice")
    registry.reload()

    studio = NarrationStudio()
    studio.load_project(proj)

    # System gracefully fell back to Kokoro-82M
    assert proj.settings.tts_engine == registry.DEFAULT_ENGINE
    assert "no longer available" in studio.lbl_engine_warning.text()


# ================================================================== 7. Model Manager Dialog UI
def test_model_manager_dialog_tabs_and_actions(qapp, tts_env, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    dlg = ModelManagerDialog(in_use=lambda: "kokoro-82m")

    # Check tabs
    assert dlg.tabs.count() == 2
    assert dlg.tabs.tabText(0) == "TTS Models Library"
    assert dlg.tabs.tabText(1) == "Imported Custom Models"

    # Check managed table has Kokoro and all 3 Qwen3 variants
    assert dlg.managed_table.rowCount() == 4
    names = [dlg.managed_table.item(r, 0).text() for r in range(4)]
    assert any("Kokoro" in n for n in names)
    assert any("Qwen3-TTS 0.6B" in n for n in names)
    assert any("Qwen3-TTS 1.7B CustomVoice" in n for n in names)
    assert any("VoiceDesign" in n for n in names)

    # Select Qwen3 0.6B row
    row_06b = next(r for r in range(4) if "0.6B" in dlg.managed_table.item(r, 0).text())
    dlg.managed_table.selectRow(row_06b)
    assert dlg.selected_managed_id() == "qwen3-tts-0.6b-customvoice"

    # Download it
    dlg._download_selected_managed()
    assert dlg.qwen3_mgr.is_model_installed("qwen3-tts-0.6b-customvoice")[0] is True

    # Verify action
    dlg._verify_selected_managed()

    # Use in Narration Studio action emits use_model signal
    selected = []
    dlg.use_model.connect(lambda mid: selected.append(mid))
    dlg._use_selected_managed()
    assert selected == ["qwen3-tts-0.6b-customvoice"]

    # Remove model
    dlg._remove_selected_managed()
    assert dlg.qwen3_mgr.is_model_installed("qwen3-tts-0.6b-customvoice")[0] is False
