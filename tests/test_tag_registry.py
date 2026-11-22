"""Comprehensive test suite for Audio Studio tag registry, multi-word tag parsing,
model-specific validation, acoustic synthesis, and UI categorization.
"""
from pathlib import Path

import numpy as np
import pytest

from src.backend.audio import studio as st
from src.backend.audio import tag_registry
from src.backend.audio.script import parse, resolve_tag
from src.backend.tts import emotion, registry
from src.backend.tts.qwen3_engine import (
    Qwen3TTSEngine,
    sanitize_text_and_extract_tags,
    translate_emotion_to_instruction,
)

# ------------------------------------------------------------------ Expected Tag Sets
EXACT_EMOTIONS = [
    "sad", "amazed", "angry", "excited", "sarcastic", "curious", "bored", "tired",
    "scornful", "panicked", "mischievously", "empathetic", "reluctantly", "crying",
    "serious", "trembling",
]

EXACT_DELIVERY_STYLES = [
    "shouting", "deep and loud shouting", "whispers", "asmr", "very slowly",
    "very fast", "like dracula",
]

EXACT_NONVERBAL_SOUNDS = [
    "gasp", "sighing", "clears throat", "giggles", "laughing", "cough", "snorts",
]

STANDARD_EMOTIONS = [
    "happy", "calm", "neutral", "friendly", "enthusiastic", "storytelling",
    "dramatic", "inspirational", "fearful", "hopeful", "satisfied",
]

ALL_REQUIRED_TAGS = EXACT_EMOTIONS + EXACT_DELIVERY_STYLES + EXACT_NONVERBAL_SOUNDS + STANDARD_EMOTIONS


# ------------------------------------------------------------------ 1. Individual Tag Tests
@pytest.mark.parametrize("tag_name", ALL_REQUIRED_TAGS)
def test_every_supported_tag_individually_in_registry(tag_name):
    """Test every supported tag individually: exists in registry, valid category, instruction, and params."""
    tag_def = tag_registry.get_tag(tag_name)
    assert tag_def is not None, f"Tag [{tag_name}] missing from tag registry!"
    assert tag_def.tag == tag_name
    assert tag_def.category in (
        tag_registry.CATEGORY_EMOTIONS,
        tag_registry.CATEGORY_DELIVERY_STYLES,
        tag_registry.CATEGORY_NONVERBAL_SOUNDS,
    )
    assert len(tag_def.label) > 0
    assert len(tag_def.description) > 0
    assert len(tag_def.instruction) > 0
    assert tag_def.speed > 0
    assert tag_def.pause > 0
    assert tag_def.expressiveness > 0
    assert tag_def.gain > 0


@pytest.mark.parametrize("tag_name", ALL_REQUIRED_TAGS)
def test_every_supported_tag_individually_parsed(tag_name):
    """Test parsing narration text with every single supported tag individually."""
    text = f"Intro. [{tag_name}] This sentence tests individual tag recognition. [/] Now back to normal."
    r = parse(text, default="neutral")
    assert len(r.segments) == 3, f"Failed to parse three segments for tag [{tag_name}]: {r.segments}"
    assert r.segments[0].emotion == "neutral"
    assert r.segments[1].emotion == tag_name
    assert r.segments[1].text == "This sentence tests individual tag recognition."
    assert r.segments[2].emotion == "neutral"
    assert r.segments[2].text == "Now back to normal."


@pytest.mark.parametrize("tag_name", ALL_REQUIRED_TAGS)
def test_every_supported_tag_individually_qwen3_instruction(tag_name):
    """Test translation to genuine instruction for every supported tag in Qwen3-TTS."""
    inst = translate_emotion_to_instruction(tag_name)
    tag_def = tag_registry.get_tag(tag_name)
    assert tag_def.instruction in inst
    assert len(inst) > 10


@pytest.mark.parametrize("tag_name", ALL_REQUIRED_TAGS)
def test_every_supported_tag_individually_qwen3_synthesis(tmp_path, tag_name):
    """Test offline acoustic waveform generation for every single supported tag individually."""
    engine = Qwen3TTSEngine(tmp_path, "qwen3-tts-0.6b-customvoice")
    text = f"[{tag_name}] Acoustic synthesis test."
    audio, sr = engine._synthesize(text, "Ryan", speed=1.0, sentence_pause=0.2, clause_pause=0.1)
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert len(audio) > 0
    assert sr == 24000
    assert not np.all(audio == 0)


# ------------------------------------------------------------------ 2. Multi-Word Tags & Brackets
def test_multi_word_tags_recognized():
    """Verify that multi-word tags with spaces are parsed and stripped correctly."""
    text = (
        "[deep and loud shouting] Listen carefully! [/] "
        "[very slowly] Do not rush. [/] "
        "[like dracula] Welcome to my castle. [/] "
        "[clears throat] Ahem. "
        "[very fast] Quick quick quick!"
    )
    r = parse(text)
    emotions = [s.emotion for s in r.segments]
    texts = [s.text for s in r.segments]
    assert emotions == ["deep and loud shouting", "very slowly", "like dracula", "clears throat", "very fast"]
    assert texts[0] == "Listen carefully!"
    assert texts[1] == "Do not rush."
    assert texts[2] == "Welcome to my castle."
    assert texts[3] == "Ahem."
    assert texts[4] == "Quick quick quick!"


def test_citations_and_brackets_preserved():
    """Verify bracketed text citations ([1], [figure 2]) are preserved while valid tags are parsed."""
    text = "Refer to [1] and [figure 2] for details. [sarcastic] As if anyone reads citations. [banana] Yes."
    r = parse(text)
    texts = [s.text for s in r.segments]
    assert "Refer to [1] and [figure 2] for details." in texts[0]
    assert texts[1] == "As if anyone reads citations."
    assert r.segments[1].emotion == "sarcastic"
    assert any("[banana]" in w for w in r.warnings)


# ------------------------------------------------------------------ 3. Model-Specific Tag Validation
def test_model_specific_tag_support_qwen3_vs_kokoro():
    """Verify model-specific tag support: Qwen3 supports all tags, Kokoro restricts nonverbal/theatrical tags."""
    # Kokoro supports emotions and basic pace styles, but not complex nonverbal sounds or theatrical styles
    kokoro_id = "kokoro-82m"
    qwen3_id = "qwen3-tts-0.6b-customvoice"

    # Supported on both
    assert tag_registry.is_tag_supported_by_model("sad", kokoro_id)
    assert tag_registry.is_tag_supported_by_model("sad", qwen3_id)
    assert tag_registry.is_tag_supported_by_model("whispers", kokoro_id)
    assert tag_registry.is_tag_supported_by_model("whispers", qwen3_id)
    assert tag_registry.is_tag_supported_by_model("very slowly", kokoro_id)
    assert tag_registry.is_tag_supported_by_model("very fast", kokoro_id)

    # Qwen3-TTS only tags (nonverbal sounds & theatrical shouting/dracula)
    qwen3_only = [
        "gasp", "sighing", "clears throat", "giggles", "laughing", "cough", "snorts",
        "shouting", "deep and loud shouting", "asmr", "like dracula",
    ]
    for tag in qwen3_only:
        assert not tag_registry.is_tag_supported_by_model(tag, kokoro_id), f"Tag [{tag}] should not be supported on Kokoro!"
        assert tag_registry.is_tag_supported_by_model(tag, qwen3_id), f"Tag [{tag}] must be supported on Qwen3-TTS!"


def test_categorized_tags_filtering_by_model():
    """Verify that get_categorized_tags separates categories and filters based on active model."""
    qwen_cats = tag_registry.get_categorized_tags("qwen3-tts-0.6b-customvoice")
    assert len(qwen_cats[tag_registry.CATEGORY_EMOTIONS]) > 0
    assert len(qwen_cats[tag_registry.CATEGORY_DELIVERY_STYLES]) == 7
    assert len(qwen_cats[tag_registry.CATEGORY_NONVERBAL_SOUNDS]) == 7

    kokoro_cats = tag_registry.get_categorized_tags("kokoro-82m")
    assert len(kokoro_cats[tag_registry.CATEGORY_EMOTIONS]) > 0
    # Kokoro only has delivery styles with speed/gain mapping (whispers, very slowly, very fast)
    assert len(kokoro_cats[tag_registry.CATEGORY_DELIVERY_STYLES]) == 3
    # Kokoro has 0 nonverbal sound tags
    assert len(kokoro_cats[tag_registry.CATEGORY_NONVERBAL_SOUNDS]) == 0


# ------------------------------------------------------------------ 4. Pre-synthesis Validation & Enforcement
def test_pre_synthesis_validation_rejects_unsupported_tags(tmp_path):
    """Verify that synthesis fails with AudioStudioError when a document contains tags unsupported by the engine."""
    lib = st.AudioLibrary(tmp_path)
    # Document with Kokoro engine and nonverbal sound [clears throat]
    doc = lib.create("Test Kokoro Unsupported", "[clears throat] Good morning everyone.")
    doc.settings.engine = "kokoro-82m"

    # Document validation returns False with clear error
    is_valid, errors = st.validate_document(doc, "kokoro-82m")
    assert not is_valid
    assert any("clears throat" in e for e in errors)
    assert any("requires Qwen3-TTS" in e for e in errors)

    # st.generate must reject synthesis
    with pytest.raises(st.AudioStudioError) as exc_info:
        st.generate(doc)
    assert "Cannot synthesize" in str(exc_info.value)

    # Switching to Qwen3-TTS makes document valid
    doc.settings.engine = "qwen3-tts-0.6b-customvoice"
    is_valid, errors = st.validate_document(doc, "qwen3-tts-0.6b-customvoice")
    assert is_valid
    assert errors == []


def test_regeneration_preserves_narration_text(tmp_path, monkeypatch):
    """Verify that regeneration makes a new take while preserving narration text."""
    from src.backend.tts.base import Capabilities, Speaker, TTSEngine

    class DummyEngine(TTSEngine):
        id, name = "dummy-qwen3", "Dummy Qwen3"
        capabilities = Capabilities(pauses=True, expressiveness=True)

        def is_installed(self):
            return True, ""

        def speakers(self):
            return [Speaker("s1", "Speaker 1", "en")]

        def _synthesize(self, text, speaker, speed, sp, cp):
            n = int(24000 * 0.2)
            return (np.sin(np.linspace(0, 10, n))).astype(np.float32), 24000

    dummy = DummyEngine()
    monkeypatch.setattr(st, "get_engine", lambda _i=None: dummy)
    from src.backend.tts import service as tts
    monkeypatch.setattr(tts, "get_engine", lambda _i=None: dummy)

    lib = st.AudioLibrary(tmp_path)
    original_text = "[excited] Welcome to Lecture Studio! [calm] Let us begin."
    doc = lib.create("Preserve Text", original_text)
    doc.settings.engine = "dummy-qwen3"

    st.generate(doc)
    assert len(doc.parsed().segments) == 2
    seg0 = doc.parsed().segments[0]
    path0 = st.segment_path(doc, seg0)
    assert path0.is_file()

    # Regenerate first segment
    st.regenerate(doc, [seg0])
    path0_t1 = st.segment_path(doc, seg0)
    assert path0_t1 != path0
    assert path0_t1.is_file()

    # Narration text is completely preserved
    assert doc.text == original_text
