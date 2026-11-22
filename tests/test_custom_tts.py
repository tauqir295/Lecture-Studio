"""Custom (user-imported) TTS models: detection, library, registry, engines, Narration Studio integration.

Real-model tests run when the files exist:
  * Kokoro-compatible import uses models/tts/kokoro-82m (installed by the app).
  * Piper uses the folder in LECTURE_STUDIO_TEST_PIPER (a voice's .onnx + .onnx.json), else skipped.
"""
import json
import os
from pathlib import Path

import numpy as np
import pytest

from src.backend.tts import registry
from src.backend.tts.custom import CustomModelStore, ModelStoreError, detect
from src.backend.tts.piper_engine import PiperEngine, phonemes_to_ids

KOKORO_DIR = registry.models_root() / "tts" / "kokoro-82m"
HAS_KOKORO = (KOKORO_DIR / "kokoro-v1.0.onnx").is_file() and (KOKORO_DIR / "voices-v1.0.bin").is_file()
PIPER_DIR = os.environ.get("LECTURE_STUDIO_TEST_PIPER", "")


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """Isolated custom-model library; registry rebuilt before and after."""
    monkeypatch.setenv("LECTURE_STUDIO_CUSTOM_MODELS", str(tmp_path / "library"))
    registry.reload()
    yield CustomModelStore()
    monkeypatch.delenv("LECTURE_STUDIO_CUSTOM_MODELS")
    registry.reload()


ID_MAP = {"_": [0], "^": [1], "$": [2], "h": [3], "ə": [4], "l": [5], "ˈ": [6], "o": [7], " ": [8], ".": [9]}


def _fake_piper(folder: Path, name="en_US-test-low", speakers=None, phoneme_type="espeak") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.onnx").write_bytes(b"not a real model")
    cfg = {"audio": {"sample_rate": 22050}, "espeak": {"voice": "en-us"}, "phoneme_type": phoneme_type,
           "inference": {"noise_scale": 0.667, "length_scale": 1, "noise_w": 0.8},
           "phoneme_id_map": ID_MAP, "num_speakers": len(speakers or {}) or 1,
           "speaker_id_map": speakers or {}, "language": {"name_english": "English", "country_english": "Test"}}
    (folder / f"{name}.onnx.json").write_text(json.dumps(cfg))
    return folder / f"{name}.onnx"


# ------------------------------------------------------------------ detection
def test_detects_piper_from_file_json_or_folder(tmp_path):
    onnx = _fake_piper(tmp_path / "voice")
    for p in (onnx, onnx.with_name(onnx.name + ".json"), onnx.parent):
        found = detect(p)
        assert len(found) == 1 and found[0].ok and found[0].format == "piper", p
        assert found[0].files["model"] == str(onnx)
        assert found[0].suggested_name == "En Us Test Low"


def test_folder_with_several_voices_lists_each(tmp_path):
    _fake_piper(tmp_path / "v", "voice_a"); _fake_piper(tmp_path / "v", "voice_b")
    assert sorted(Path(d.files["model"]).name for d in detect(tmp_path / "v")) == ["voice_a.onnx", "voice_b.onnx"]


def test_unsupported_piper_phoneme_type_is_not_importable(tmp_path):
    _fake_piper(tmp_path / "v", phoneme_type="text")
    d = detect(tmp_path / "v")
    assert not any(x.ok for x in d)


@pytest.mark.parametrize("files,expect", [
    (["model.pth", "config.json"], "PyTorch"),
    (["model.safetensors", "config.json"], "Hugging Face"),
    (["tokens.txt", "model.onnx"], "sherpa-onnx"),
    (["voice.gguf"], "GGUF"),
    (["lonely.onnx"], "not a Piper voice or a Kokoro model"),
    (["readme.txt"], "No supported TTS model"),
])
def test_unsupported_formats_explain_how_to_fix(tmp_path, files, expect):
    for f in files:
        (tmp_path / f).write_bytes(b"x")
    d = detect(tmp_path)
    assert len(d) == 1 and not d[0].ok and expect in d[0].message
    assert "Supported formats" in d[0].instructions


def test_missing_path():
    assert not detect("/definitely/not/here")[0].ok


# ------------------------------------------------------------------ library
def test_store_add_rename_remove_in_place(lib, tmp_path):
    onnx = _fake_piper(tmp_path / "v")
    det = detect(onnx)[0]
    e = lib.add(det, "My Voice", copy=False, license_note="CC-BY")
    assert e["id"] == "custom-my-voice" and not e["managed"] and e["license"] == "CC-BY"
    with pytest.raises(ModelStoreError):
        lib.add(det, "my voice")                                # names are unique (case-insensitive)
    assert lib.add(det, "Second")["id"] == "custom-second"
    lib.rename(e["id"], "Renamed")
    assert lib.get(e["id"])["name"] == "Renamed"
    with pytest.raises(ModelStoreError):
        lib.rename(e["id"], "Second")
    lib.remove(e["id"], delete_files=True)                      # in-place originals are never deleted
    assert lib.get(e["id"]) is None and onnx.is_file()


def test_store_copy_into_library_and_delete_copy(lib, tmp_path):
    onnx = _fake_piper(tmp_path / "v")
    steps = []
    e = lib.add(detect(onnx)[0], "Copied", copy=True, progress=lambda p, m: steps.append(p))
    copy_dir = lib.root / e["id"]
    assert e["managed"] and Path(e["files"]["model"]).parent == copy_dir.resolve() and steps[-1] == 100
    onnx.unlink()                                               # original gone: copy still registered/valid
    assert lib.missing_files(e) == []
    lib.remove(e["id"], delete_files=True)
    assert not copy_dir.exists()


def test_corrupt_library_file_is_ignored(lib):
    lib.root.mkdir(parents=True)
    lib.file.write_text("{oops")
    assert lib.entries() == []


# ------------------------------------------------------------------ registry
def test_registry_lists_custom_engines_and_falls_back(lib, tmp_path):
    e = lib.add(detect(_fake_piper(tmp_path / "v", speakers={"alice": 0, "bob": 1}))[0], "Duo")
    registry.reload()
    assert registry.has_engine(e["id"])
    eng = registry.get_engine(e["id"])
    assert eng.custom and isinstance(eng, PiperEngine) and not eng.downloadable
    assert [s.id for s in eng.speakers()] == ["alice", "bob"]
    assert registry.get_engine("kokoro-82m").id == "kokoro-82m"            # default untouched
    lib.remove(e["id"]); registry.reload()
    assert not registry.has_engine(e["id"])
    assert registry.get_engine(e["id"]).id == registry.DEFAULT_ENGINE      # removed model -> default


# ------------------------------------------------------------------ piper engine (mocked runtime)
def test_phonemes_to_ids_matches_piper_encoding():
    assert phonemes_to_ids("hə", ID_MAP) == [1, 0, 3, 0, 4, 0, 2]
    assert phonemes_to_ids("h?", ID_MAP) == [1, 0, 3, 0, 2]                # unknown phoneme skipped
    assert phonemes_to_ids("x", ID_MAP, {"x": ["h", "o"]}) == [1, 0, 3, 0, 7, 0, 2]


def test_piper_synthesis_feeds_model_correctly(tmp_path, monkeypatch):
    onnx = _fake_piper(tmp_path / "v", speakers={"alice": 0, "bob": 1})
    eng = PiperEngine(onnx, onnx.with_name(onnx.name + ".json"), "custom-t", "T")
    seen = []

    class Inp:
        def __init__(self, n): self.name = n

    class Sess:
        def get_inputs(self): return [Inp("input"), Inp("input_lengths"), Inp("scales"), Inp("sid")]
        def run(self, _out, feed):
            seen.append(feed)
            return [np.full((1, 1, 2205), 0.5, dtype=np.float32)]

    monkeypatch.setattr(eng, "_load", lambda: setattr(eng, "_session", Sess()))
    monkeypatch.setattr(eng, "phonemize", lambda t: "həlˈo.")
    audio, sr = eng.synthesize("Hello. Hello again!", "bob", speed=2.0)
    assert sr == 22050 and len(seen) == 2                                  # one run per sentence
    assert seen[0]["sid"].tolist() == [1]
    assert seen[0]["scales"].tolist() == pytest.approx([0.667, 0.5, 0.8])   # speed 2x -> length_scale 0.5
    assert seen[0]["input"].dtype == np.int64 and seen[0]["input_lengths"].tolist() == [seen[0]["input"].shape[1]]
    assert len(audio) == 2 * 2205 + int(22050 * 0.25)                      # sentences + one gap


# ------------------------------------------------------------------ real models
@pytest.mark.skipif(not HAS_KOKORO, reason="Kokoro model not installed")
def test_import_kokoro_compatible_model_and_narrate(lib, tmp_path):
    from src.backend.tts import service as tts
    from src.models.narration import SlideNarration
    from src.models.project import Project
    from src.models.slide import Slide
    found = detect(KOKORO_DIR)
    assert found[0].ok and found[0].format == "kokoro" and found[0].speakers > 20
    e = lib.add(found[0], "My Kokoro Build")
    registry.reload()
    eng = registry.get_engine(e["id"])
    assert eng.custom and not eng.downloadable and eng.find_speaker("am_michael")

    proj = Project(project_id="p", project_name="P", project_dir=str(tmp_path / "proj"))
    proj.settings.tts_engine, proj.settings.voice_id = e["id"], "af_heart"
    proj.settings.speaker_mode = "per_slide"
    proj.slides = [Slide(slide_id="s1", slide_number=1, title="A"), Slide(slide_id="s2", slide_number=2, title="B")]
    proj.narrations = [SlideNarration(slide_id="s1", slide_number=1, script="First slide."),
                       SlideNarration(slide_id="s2", slide_number=2, script="Second slide.", speaker="am_michael")]
    for n in proj.narrations:
        tts.generate_slide_audio(proj, n)
        assert tts.audio_state(proj, n) == tts.READY and n.audio_duration > 0.3
    assert tts.options_for(proj, proj.narrations[1]).speaker == "am_michael"   # per-slide speaker honoured
    assert tts.options_for(proj, proj.narrations[1]).engine == e["id"]
    assert tts.sample_audio(proj, "bf_emma").is_file()
    assert tts.preview_audio(proj, "Unsaved text, read aloud.").is_file()


@pytest.mark.skipif(not (PIPER_DIR and Path(PIPER_DIR).is_dir()), reason="set LECTURE_STUDIO_TEST_PIPER to a Piper voice folder")
def test_real_piper_voice_end_to_end(lib, tmp_path):
    found = detect(PIPER_DIR)
    e = lib.add(found[0], "Real Piper", copy=False)
    registry.reload()
    eng = registry.get_engine(e["id"])
    sp = eng.speakers()[0].id
    audio, sr = eng.synthesize("This narration was generated offline by an imported Piper voice.", sp)
    secs = len(audio) / sr
    assert 2.0 < secs < 12.0 and float(np.abs(audio).max()) > 0.05


# ------------------------------------------------------------------ UI
def test_model_manager_import_rename_remove(qapp, lib, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from src.frontend.model_manager import ModelManagerDialog
    shown = []
    dlg = ModelManagerDialog(store=lib)
    dlg.show_problem = lambda title, det: shown.append(det.message)
    dlg.ask_import_options = lambda det: {"name": "Lab Voice", "copy": False, "license_note": ""}
    changed = []
    dlg.models_changed.connect(lambda: changed.append(1))

    (tmp_path / "junk").mkdir(); (tmp_path / "junk" / "model.pth").write_bytes(b"x")
    assert dlg.import_path(str(tmp_path / "junk")) is None and "PyTorch" in shown[0]

    e = dlg.import_path(str(_fake_piper(tmp_path / "v")))
    assert e and dlg.table.rowCount() == 1 and changed and registry.has_engine(e["id"])
    assert dlg.table.item(0, 1).text() == "piper"

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    assert dlg.rename_model(e["id"], "Lab Voice 2") and "Lab Voice 2" in dlg.table.item(0, 0).text()
    dlg.remove_model(e["id"])
    assert dlg.table.rowCount() == 0 and not registry.has_engine(e["id"])


def test_narration_studio_uses_and_survives_removed_custom_model(qapp, lib, tmp_path):
    from src.frontend.narration_studio import NarrationStudio
    from src.models.narration import SlideNarration
    from src.models.project import Project
    from src.models.slide import Slide
    e = lib.add(detect(_fake_piper(tmp_path / "v", speakers={"alice": 0, "bob": 1}))[0], "Duo")
    registry.reload()
    proj = Project(project_id="p", project_name="P", project_dir=str(tmp_path / "proj"))
    proj.slides = [Slide(slide_id="s1", slide_number=1, title="A")]
    proj.narrations = [SlideNarration(slide_id="s1", slide_number=1, script="Hi.")]
    ns = NarrationStudio()
    ns.load_project(proj)
    assert ns.combo_engine.findData(e["id"]) >= 0                         # custom model offered
    ns.select_engine(e["id"])
    assert proj.settings.tts_engine == e["id"] and proj.settings.voice_id == "alice"
    assert [ns.combo_speaker.itemData(i) for i in range(ns.combo_speaker.count())][:2] == ["alice", "bob"]

    lib.remove(e["id"])
    ns._on_models_changed()                                                # what the manager triggers
    assert proj.settings.tts_engine == registry.DEFAULT_ENGINE
    assert "no longer available" in ns.lbl_engine_warning.text()
    assert ns.combo_engine.findData(e["id"]) == -1
