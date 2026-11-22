"""Audio Studio: emotion tags, segment generation & partial regeneration, assembly, exports, UI."""
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest

from src.backend.audio import studio as st
from src.backend.audio.script import parse, resolve_tag
from src.backend.tts import emotion, registry
from src.backend.tts import service as tts
from src.backend.tts.base import Capabilities, Speaker, TTSEngine
from src.backend.video.pipeline import ffmpeg_path

KOKORO_DIR = registry.models_root() / "tts" / "kokoro-82m"
HAS_KOKORO = (KOKORO_DIR / "kokoro-v1.0.onnx").is_file()
TAGS = ["happy", "sad", "excited", "angry", "calm", "fearful", "whispering", "dramatic", "hopeful", "serious",
        "storytelling", "satisfied"]


# ------------------------------------------------------------------ tags
def test_all_requested_tags_are_styles():
    assert all(resolve_tag(t) == t for t in TAGS)
    assert resolve_tag("WHISPER") == "whispering" and resolve_tag("joyful") == "happy"
    assert resolve_tag("banana") == ""


def test_parse_paragraph_and_sentence_tags():
    r = parse("[storytelling] One. Two!\n\n[happy] Three. [sad] Four? [/] Five.\n\nSix.", default="calm")
    assert [(s.text, s.emotion, s.paragraph) for s in r.segments] == [
        ("One.", "storytelling", 0), ("Two!", "storytelling", 0),
        ("Three.", "happy", 1), ("Four?", "sad", 1), ("Five.", "happy", 1),   # [/] -> paragraph style
        ("Six.", "calm", 2)]                                                  # untagged -> default
    assert r.warnings == []


def test_mid_sentence_tag_splits_and_pauses():
    r = parse("Hello there [whispering] quietly now. [pause 2.5s] Back. [pause] [pause 30s]")
    assert [(s.text, s.emotion, s.pause_before) for s in r.segments] == [
        ("Hello there", "neutral", 0.0), ("quietly now.", "whispering", 0.0), ("Back.", "whispering", 2.5)]
    assert r.trailing_pause == pytest.approx(1.0 + 10.0)                      # pauses capped at 10 s


def test_unknown_tags_brackets_and_emphasis():
    r = parse("See [1] and [figure 2]. [banana] Yes. This is *really* important.")
    texts = [s.text for s in r.segments]
    assert texts[0] == "See [1] and [figure 2]." and "really important" in texts[-1] and "*" not in texts[-1]
    assert any("[banana]" in w for w in r.warnings)


def test_whispering_lowers_volume_and_styles_scale_pace():
    w, sad, exc = emotion.get("whispering"), emotion.get("sad"), emotion.get("excited")
    assert w.gain < 1 and sad.speed < 1 < exc.speed and sad.pause > 1 > exc.pause


# ------------------------------------------------------------------ fake engine for fast, deterministic tests
class Beep(TTSEngine):
    id, name = "beep", "Beep"
    capabilities = Capabilities(pauses=True, expressiveness=True)

    def __init__(self):
        super().__init__()
        self.calls = []

    def is_installed(self):
        return True, ""

    def speakers(self):
        return [Speaker("b1", "Beep 1", "English (US)"), Speaker("b2", "Beep 2", "English (US)")]

    def _synthesize(self, text, speaker, speed, sp, cp):
        self.calls.append((text, speed, self._expressiveness))
        n = int(24000 * 0.5 * len(text.split()) / speed)                   # 0.5 s per word
        t = np.arange(n) / 24000
        return (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), 24000


@pytest.fixture
def beep(monkeypatch):
    eng = Beep()
    monkeypatch.setattr(st, "get_engine", lambda _i=None: eng)
    monkeypatch.setattr(tts, "get_engine", lambda _i=None: eng)
    return eng


@pytest.fixture
def doc(tmp_path, beep):
    lib = st.AudioLibrary(tmp_path)
    d = lib.create("Test Doc", "[happy] One two. [sad] Three four.\n\n[pause 1s] Five six.")
    d.settings.engine, d.settings.sentence_gap, d.settings.paragraph_gap = "beep", 0.25, 0.75
    return d


def test_generate_caches_and_regenerates_only_changes(doc, beep):
    assert st.generate(doc) == [0, 1, 2] and len(beep.calls) == 3
    happy, sad = beep.calls[0], beep.calls[1]
    assert happy[1] == pytest.approx(1.05) and sad[1] == pytest.approx(0.86)    # style pace applied
    assert happy[2] == pytest.approx(1.2)                                       # expressiveness applied
    assert st.generate(doc) == [] and len(beep.calls) == 3                      # cached

    doc.text = doc.text.replace("Three four.", "Three four five.")             # edit one sentence
    assert st.generate(doc) == [1] and len(beep.calls) == 4

    seg = doc.parsed().segments[0]
    before = st.segment_path(doc, seg)
    assert st.regenerate(doc, [seg]) == [0] and len(beep.calls) == 5           # forced new take
    assert st.segment_path(doc, seg) != before and st.segment_path(doc, seg).is_file()


def test_changing_voice_settings_invalidates_cache(doc, beep):
    st.generate(doc)
    doc.settings.speaker = "b2"
    assert st.generate(doc) == [0, 1, 2]


def test_assemble_timeline_gaps_and_pauses(doc):
    st.generate(doc)
    audio, sr, tl = st.assemble(doc)
    d0 = 2 * 0.5 / 1.05                                      # "One two." happy
    d1 = 2 * 0.5 / 0.86                                      # "Three four." sad
    assert tl[0].start == 0 and tl[0].end == pytest.approx(d0, abs=0.01)
    assert tl[1].start == pytest.approx(d0 + 0.25, abs=0.01)                    # sentence gap
    assert tl[2].start == pytest.approx(tl[1].end + 0.75 + 1.0, abs=0.01)       # paragraph gap + [pause 1s]
    assert len(audio) / sr == pytest.approx(tl[2].end, abs=0.01)
    assert [t.emotion for t in tl] == ["happy", "sad", "neutral"]
    p = st.peaks(audio, 100)
    assert len(p) == 100 and p.max() <= 1.0 and p.max() > 0.3


def test_assemble_requires_generated_audio(doc):
    with pytest.raises(st.AudioStudioError):
        st.assemble(doc)


def test_documents_persist(tmp_path, doc):
    doc.takes["k"] = 2
    st.AudioLibrary(tmp_path).save(doc)
    again = st.AudioLibrary(tmp_path).list()[0]
    assert again.text == doc.text and again.settings.paragraph_gap == 0.75 and again.takes == {"k": 2}
    st.AudioLibrary(tmp_path).delete(again)
    assert st.AudioLibrary(tmp_path).list() == []


# ------------------------------------------------------------------ export
def _probe(path: Path):
    err = subprocess.run([ffmpeg_path(), "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    a = re.search(r"Audio: (\w+).*?(\d+) Hz, (mono|stereo)", err)
    return int(h) * 3600 + int(m) * 60 + float(s), a.group(1), int(a.group(2)), a.group(3)


@pytest.mark.skipif(ffmpeg_path() is None, reason="ffmpeg not available")
@pytest.mark.parametrize("fmt,rate,channels,codec", [
    ("wav", 44100, 1, "pcm_s16le"), ("flac", 48000, 2, "flac"), ("mp3", 44100, 2, "mp3"),
    ("m4a", 44100, 1, "aac"), ("ogg", 32000, 1, "vorbis"), ("opus", 48000, 1, "opus"), ("alac", 44100, 1, "alac")])
def test_export_formats(doc, fmt, rate, channels, codec):
    if fmt not in {f.key for f in st.available_formats()}:
        pytest.skip(f"{fmt} encoder not in this ffmpeg")
    st.generate(doc)
    audio, sr, _ = st.assemble(doc)
    out = st.export(doc, fmt, 0, rate, channels)
    _dur, c, r, ch = _probe(out)
    assert c.startswith(codec) and r == rate and ch == ("mono" if channels == 1 else "stereo")
    # decoded length (container headers may report encoder framing/padding)
    raw = subprocess.run([ffmpeg_path(), "-loglevel", "error", "-i", str(out), "-f", "s16le", "-ac", "1",
                          "-ar", str(rate), "-"], capture_output=True).stdout
    assert len(raw) / 2 / rate == pytest.approx(len(audio) / sr, abs=0.01)


def test_export_rejects_bad_rate_and_unknown_format(doc):
    st.generate(doc)
    with pytest.raises(st.AudioStudioError):
        st.export(doc, "opus", 0, 44100)
    with pytest.raises(st.AudioStudioError):
        st.export(doc, "aiff-x", 0, 44100)


# ------------------------------------------------------------------ real & custom models
@pytest.mark.skipif(not HAS_KOKORO, reason="Kokoro model not installed")
def test_kokoro_tags_change_delivery_and_custom_model_works(tmp_path, monkeypatch):
    from src.backend.tts.custom import CustomModelStore, detect
    lib = st.AudioLibrary(tmp_path)
    line = "The results are in, and the numbers are clear."
    d = lib.create("Real", f"[excited] {line}\n\n[sad] {line}\n\n[whispering] {line}")
    d.settings.speaker = "af_heart"
    st.generate(d)
    audio, sr, tl = st.assemble(d)
    lens = [t.end - t.start for t in tl]
    assert lens[1] > lens[0] * 1.15                                     # sad is clearly slower than excited
    seg = lambda i: audio[int(tl[i].start * sr):int(tl[i].end * sr)]
    assert np.abs(seg(2)).max() < np.abs(seg(1)).max() * 0.8            # whispering is quieter

    monkeypatch.setenv("LECTURE_STUDIO_CUSTOM_MODELS", str(tmp_path / "models"))
    registry.reload()
    try:
        e = CustomModelStore().add(detect(KOKORO_DIR)[0], "My Kokoro")
        registry.reload()
        d.settings.engine, d.settings.speaker = e["id"], "bm_george"
        assert st.generate(d) == [0, 1, 2]                              # new model -> new audio
        assert st.export(d, "mp3", 2, 44100, 1).is_file()
    finally:
        monkeypatch.delenv("LECTURE_STUDIO_CUSTOM_MODELS")
        registry.reload()


# ------------------------------------------------------------------ UI
def test_audio_studio_ui(qapp, tmp_path, beep, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from src.frontend.audio_studio import AudioStudio
    ui = AudioStudio(tmp_path)
    assert not (tmp_path / "Audio").exists()                            # nothing written until shown
    ui.refresh_documents()
    assert ui.doc and "[storytelling]" in ui.editor.toPlainText()       # example document created
    ui.editor.setPlainText("Plain sentence here. Another one.")
    ui._on_text_settled()
    assert ui.table.rowCount() == 2 and ui.table.item(0, 4).text() == "not generated"

    from PySide6.QtGui import QTextCursor
    cur = ui.editor.textCursor(); cur.setPosition(0)
    cur.setPosition(20, QTextCursor.MoveMode.KeepAnchor); ui.editor.setTextCursor(cur)
    ui.combo_tag.setCurrentIndex(ui.combo_tag.findData("angry"))
    ui.insert_tag()
    assert ui.editor.toPlainText().startswith("[angry] Plain sentence here. [/]")
    ui._on_text_settled()
    assert ui.table.item(0, 1).text() == "Angry"

    ui.doc.settings.engine = "beep"
    ui.generate_missing(); ui.worker.wait(); QApplication.processEvents()
    assert all(ui.table.item(r, 4).text() == "ready" for r in range(ui.table.rowCount()))
    assert ui.wave.total > 0 and len(ui.wave.timeline) == 2

    n = len(beep.calls)
    ui.table.selectRow(1)
    ui.regenerate_selected(); ui.worker.wait(); QApplication.processEvents()
    assert len(beep.calls) == n + 1

    if "mp3" in {f.key for f in st.available_formats()}:
        ui.combo_fmt.setCurrentIndex(ui.combo_fmt.findData("mp3"))
        out = tmp_path / "out.mp3"
        ui.export_to(out); ui.worker.wait(); QApplication.processEvents()
        assert out.is_file() and "Exported" in ui.lbl_status.text()
