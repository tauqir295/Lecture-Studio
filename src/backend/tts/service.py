"""Narration audio service: per-slide speaker resolution, caching, generation, staleness."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import numpy as np

from src.backend.tts import emotion
from src.backend.tts.registry import get_engine
from src.models.narration import SlideNarration
from src.models.project import Project

NONE, READY, OUTDATED, MISSING = "none", "ready", "outdated", "missing"


@dataclass(frozen=True)
class TTSOptions:
    engine: str
    speaker: str
    speed: float = 1.0
    sentence_pause: float = 0.3
    clause_pause: float = 0.1
    emotion: str = emotion.NEUTRAL

    def as_dict(self) -> Dict:
        """Options as stored in audio metadata / cache keys. Neutral style is left out so audio made
        before styles existed is still recognised as up to date."""
        d = asdict(self)
        if d.get("emotion") == emotion.NEUTRAL:
            d.pop("emotion")
        return d

    def key(self, text: str) -> str:
        payload = json.dumps({**self.as_dict(), "text": text}, sort_keys=True)
        return hashlib.sha1(payload.encode()).hexdigest()[:20]


# ------------------------------------------------------------------ text preparation
def clean_text(script: str) -> str:
    """Remove markdown symbols; words are never dropped."""
    t = re.sub(r"[*_`#]+", " ", script or "")
    return re.sub(r"\s+", " ", t).strip()


def apply_pronunciations(text: str, mapping: Dict[str, str]) -> str:
    """Replace whole terms with their spoken form (longest first, case-sensitive)."""
    for term in sorted(mapping or {}, key=len, reverse=True):
        say = mapping[term]
        if term and say:
            text = re.sub(rf"(?<![\w.]){re.escape(term)}(?![\w])", say, text)
    return text


def spoken_text(project: Project, script: str) -> str:
    return apply_pronunciations(clean_text(script), project.settings.pronunciations)


# ------------------------------------------------------------------ options
def global_options(project: Project, speaker: Optional[str] = None, style: Optional[str] = None) -> TTSOptions:
    cfg = project.settings
    eng = get_engine(cfg.tts_engine)
    spk = speaker or cfg.voice_id
    if not eng.find_speaker(spk):
        spk = eng.default_speaker()
    pauses = eng.capabilities.pauses
    return TTSOptions(eng.id, spk, float(cfg.speech_speed),
                      cfg.sentence_pause if pauses else 0.0, cfg.clause_pause if pauses else 0.0,
                      emotion.get(style or cfg.emotion).key)


def slide_speaker(project: Project, narration: SlideNarration) -> str:
    if project.settings.speaker_mode == "per_slide" and narration.speaker:
        return narration.speaker
    return project.settings.voice_id


def slide_emotion(project: Project, narration: Optional[SlideNarration]) -> str:
    """The slide's own delivery style, else the project's."""
    if narration is not None and narration.emotion:
        return emotion.get(narration.emotion).key
    return emotion.get(project.settings.emotion).key


def options_for(project: Project, narration: SlideNarration) -> TTSOptions:
    return global_options(project, slide_speaker(project, narration), slide_emotion(project, narration))


# ------------------------------------------------------------------ synthesis
def _write_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    import soundfile as sf
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.wav")
    sf.write(str(tmp), audio, sr, subtype="PCM_16")
    tmp.replace(path)


def wav_seconds(path: Path) -> float:
    import soundfile as sf
    info = sf.info(str(path))
    return info.frames / float(info.samplerate)


def synthesize_cached(text: str, opts: TTSOptions, cache_dir: Path) -> Path:
    """Synthesize `text` (already prepared) once per (text, options); return the WAV path."""
    out = Path(cache_dir) / f"{opts.engine}_{opts.key(text)}.wav"
    if out.is_file() and out.stat().st_size > 44:
        return out
    eng = get_engine(opts.engine)
    a = emotion.apply(opts.emotion, eng, opts.speed, opts.sentence_pause, opts.clause_pause)
    audio, sr = eng.synthesize(text, opts.speaker, a.speed, a.sentence_pause, a.clause_pause,
                               a.expressiveness, a.native_style)
    if a.gain != 1.0:
        audio = np.clip(np.asarray(audio, dtype=np.float32) * a.gain, -1.0, 1.0)
    if audio.size == 0:
        audio = np.zeros(int(sr * 0.2), dtype=np.float32)
    _write_wav(out, audio, sr)
    return out


def cache_dir(project: Project) -> Path:
    return Path(project.project_dir) / "audio" / "cache"


def sample_audio(project: Project, speaker: Optional[str] = None, engine: Optional[str] = None) -> Path:
    opts = global_options(project, speaker)
    if engine:
        eng = get_engine(engine)
        opts = TTSOptions(eng.id, speaker or eng.default_speaker(), opts.speed,
                          opts.sentence_pause if eng.capabilities.pauses else 0.0,
                          opts.clause_pause if eng.capabilities.pauses else 0.0, opts.emotion)
    text = get_engine(opts.engine).sample_sentence(opts.speaker)
    return synthesize_cached(text, opts, cache_dir(project) / "samples")


def preview_audio(project: Project, script: str, speaker: Optional[str] = None,
                  style: Optional[str] = None) -> Path:
    """Speak arbitrary (possibly unsaved) narration text with the given/global speaker and style."""
    opts = global_options(project, speaker, style)
    return synthesize_cached(spoken_text(project, script), opts, cache_dir(project))


# ------------------------------------------------------------------ per-slide audio
def _meta(project: Project, narration: SlideNarration) -> Dict:
    opts = options_for(project, narration)
    text = spoken_text(project, narration.script)
    return {**opts.as_dict(), "text_sha": hashlib.sha1(text.encode()).hexdigest()[:16]}


def slide_audio_path(project: Project, narration: SlideNarration) -> Optional[Path]:
    if not narration.audio_path:
        return None
    return Path(project.project_dir) / narration.audio_path


def audio_state(project: Project, narration: SlideNarration) -> str:
    """none (never generated) · missing (file gone) · outdated (text/voice changed) · ready."""
    path = slide_audio_path(project, narration)
    if path is None:
        return NONE
    if not path.is_file():
        return MISSING
    return READY if narration.audio_meta == _meta(project, narration) else OUTDATED


def generate_slide_audio(project: Project, narration: SlideNarration) -> SlideNarration:
    """(Re)generate one slide's narration audio and store it as audio/slide_###.wav."""
    opts = options_for(project, narration)
    text = spoken_text(project, narration.script)
    if not text:
        raise ValueError(f"Slide {narration.slide_number} has no narration text.")
    src = synthesize_cached(text, opts, cache_dir(project))
    rel = f"audio/slide_{narration.slide_number:03d}.wav"
    dest = Path(project.project_dir) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    narration.audio_path = rel
    narration.audio_duration = round(wav_seconds(dest), 3)
    narration.audio_status = READY
    narration.audio_meta = _meta(project, narration)
    narration.error_message = None
    return narration


def generate_many(project: Project, narrations: Iterable[SlideNarration],
                  progress: Callable[[int, str], None] = lambda p, m: None,
                  cancel: Callable[[], bool] = lambda: False) -> List[int]:
    """Generate audio for several slides; returns slide numbers that were generated."""
    items = list(narrations)
    done = []
    for i, n in enumerate(items, 1):
        if cancel():
            break
        progress(int((i - 1) / max(len(items), 1) * 100), f"Generating slide {n.slide_number} ({i}/{len(items)})…")
        if not n.script.strip():
            continue
        try:
            generate_slide_audio(project, n)
            done.append(n.slide_number)
        except Exception as exc:
            n.audio_status, n.error_message = "failed", str(exc)
            raise
    progress(100, f"Generated audio for {len(done)} slide(s).")
    return done
