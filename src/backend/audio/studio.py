"""Standalone narration audio: documents, segment synthesis, assembly, export. No Qt, no video project.

    <workspace>/Audio/<doc-id>/document.json   text + voice settings
                              cache/           one WAV per (segment text, voice settings) - reused
                              exports/         exported files

Generation is per sentence segment and cached, so after editing only changed sentences are
synthesized again; `regenerate` forces new takes for chosen segments.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import numpy as np

from src.backend.audio.script import ParseResult, Segment, parse
from src.backend.tts import emotion
from src.backend.tts import service as tts
from src.backend.tts.registry import get_engine
from src.utils.file_utils import atomic_write_json
from src.utils.process_utils import no_window_kwargs

Progress = Callable[[int, str], None]


class AudioStudioError(RuntimeError):
    pass


# ------------------------------------------------------------------ document
@dataclass
class AudioSettings:
    engine: str = "kokoro-82m"
    speaker: str = ""
    speed: float = 1.0
    sentence_pause: float = 0.3      # inside a segment (engines with pause control)
    clause_pause: float = 0.1
    default_emotion: str = emotion.NEUTRAL
    sentence_gap: float = 0.35       # silence between sentence segments
    paragraph_gap: float = 0.9       # silence between paragraphs
    pronunciations: Dict[str, str] = field(default_factory=dict)


@dataclass
class AudioDocument:
    doc_id: str
    name: str
    text: str = ""
    settings: AudioSettings = field(default_factory=AudioSettings)
    takes: Dict[str, int] = field(default_factory=dict)   # segment cache key -> take number (regenerations)
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated: str = ""
    folder: str = ""

    def to_dict(self) -> Dict:
        d = asdict(self)
        d.pop("folder")
        return d

    @classmethod
    def from_dict(cls, data: Dict, folder: str = "") -> "AudioDocument":
        s = AudioSettings(**{k: v for k, v in (data.get("settings") or {}).items()
                             if k in AudioSettings.__dataclass_fields__})
        return cls(doc_id=data["doc_id"], name=data.get("name", data["doc_id"]), text=data.get("text", ""),
                   settings=s, takes=dict(data.get("takes") or {}), created=data.get("created", ""),
                   updated=data.get("updated", ""), folder=folder)

    @property
    def path(self) -> Path:
        return Path(self.folder)

    @property
    def cache(self) -> Path:
        return self.path / "cache"

    @property
    def exports(self) -> Path:
        return self.path / "exports"

    def parsed(self, model_id: Optional[str] = None) -> ParseResult:
        return parse(self.text, self.settings.default_emotion, model_id or self.settings.engine)


class AudioLibrary:
    """Audio documents stored under <workspace>/Audio."""

    def __init__(self, workspace: Path):
        self.root = Path(workspace) / "Audio"

    def list(self) -> List[AudioDocument]:
        docs = []
        if self.root.is_dir():
            for d in self.root.iterdir():
                if (d / "document.json").is_file():
                    try:
                        docs.append(self.load(d))
                    except Exception:
                        continue
        return sorted(docs, key=lambda x: x.updated or x.created, reverse=True)

    def create(self, name: str, text: str = "", settings: Optional[AudioSettings] = None) -> AudioDocument:
        name = (name or "").strip() or "Narration"
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "narration"
        did, i = slug, 2
        while (self.root / did).exists():
            did, i = f"{slug}-{i}", i + 1
        doc = AudioDocument(did, name, text, settings or AudioSettings(), folder=str(self.root / did))
        self.save(doc)
        return doc

    def load(self, folder: Path) -> AudioDocument:
        data = json.loads((Path(folder) / "document.json").read_text(encoding="utf-8"))
        return AudioDocument.from_dict(data, str(folder))

    def save(self, doc: AudioDocument) -> None:
        doc.updated = datetime.now().isoformat(timespec="seconds")
        doc.path.mkdir(parents=True, exist_ok=True)
        atomic_write_json(doc.path / "document.json", doc.to_dict())

    def delete(self, doc: AudioDocument) -> None:
        p = doc.path.resolve()
        if p.parent == self.root.resolve() and (p / "document.json").is_file():
            shutil.rmtree(p, ignore_errors=True)


# ------------------------------------------------------------------ synthesis
def _options(doc: AudioDocument, seg: Segment) -> tts.TTSOptions:
    s = doc.settings
    eng = get_engine(s.engine)
    spk = s.speaker if eng.find_speaker(s.speaker) else eng.default_speaker()
    pauses = eng.capabilities.pauses
    return tts.TTSOptions(eng.id, spk, float(s.speed), s.sentence_pause if pauses else 0.0,
                          s.clause_pause if pauses else 0.0, emotion.get(seg.emotion).key)


def _spoken(doc: AudioDocument, seg: Segment) -> str:
    return tts.apply_pronunciations(tts.clean_text(seg.text), doc.settings.pronunciations)


def segment_key(doc: AudioDocument, seg: Segment) -> str:
    return _options(doc, seg).key(_spoken(doc, seg))


def segment_path(doc: AudioDocument, seg: Segment) -> Path:
    key = segment_key(doc, seg)
    take = doc.takes.get(key, 0)
    return doc.cache / f"{key}{'' if take == 0 else f'_t{take}'}.wav"


def segment_ready(doc: AudioDocument, seg: Segment) -> bool:
    p = segment_path(doc, seg)
    return p.is_file() and p.stat().st_size > 44


def validate_document(doc: AudioDocument, engine_id: Optional[str] = None) -> Tuple[bool, List[str]]:
    """Validate all tags in an AudioDocument against the target TTS engine.

    Returns:
        (is_valid, list_of_error_messages)
    """
    from src.backend.audio import tag_registry
    eid = engine_id or doc.settings.engine
    pr = doc.parsed(eid)
    errors: List[str] = []

    # Check default emotion setting
    if doc.settings.default_emotion:
        t = tag_registry.get_tag(doc.settings.default_emotion)
        if t and not t.is_supported_by(eid):
            errors.append(f"Default style [{t.tag}] is not supported by {eid} (requires Qwen3-TTS).")

    # Check warnings for unsupported tags
    for w in pr.warnings:
        if "not supported by" in w:
            errors.append(w)

    # Check each segment's emotion
    for seg in pr.segments:
        if seg.emotion:
            t = tag_registry.get_tag(seg.emotion)
            if t and not t.is_supported_by(eid):
                msg = f"Segment {seg.index + 1} uses tag [{t.tag}], which is not supported by {eid} (requires Qwen3-TTS)."
                if msg not in errors:
                    errors.append(msg)

    return len(errors) == 0, errors


def synthesize_segment(doc: AudioDocument, seg: Segment) -> Path:
    from src.backend.audio import tag_registry
    eid = doc.settings.engine
    if seg.emotion:
        t = tag_registry.get_tag(seg.emotion)
        if t and not t.is_supported_by(eid):
            raise AudioStudioError(f"Cannot synthesize: tag [{t.tag}] is not supported by {eid} (requires Qwen3-TTS).")
    out = segment_path(doc, seg)
    if out.is_file() and out.stat().st_size > 44:
        return out
    tmp = doc.cache / "_tmp"
    src = tts.synthesize_cached(_spoken(doc, seg), _options(doc, seg), tmp)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(out))
    return out


def generate(doc: AudioDocument, segments: Optional[Iterable[Segment]] = None, progress: Optional[Progress] = None,
             cancel: Callable[[], bool] = lambda: False) -> List[int]:
    """Synthesize segments that have no audio yet (all, or the given ones). Returns generated indexes."""
    ok, errors = validate_document(doc)
    if not ok:
        raise AudioStudioError(f"Cannot synthesize: {errors[0]}")
    progress = progress or (lambda p, m: None)
    segs = list(segments) if segments is not None else doc.parsed().segments
    todo = [s for s in segs if not segment_ready(doc, s)]
    done = []
    for i, seg in enumerate(todo, 1):
        if cancel():
            break
        progress(int(100 * (i - 1) / max(len(todo), 1)), f"Segment {seg.index + 1}: {seg.label} ({i}/{len(todo)})")
        synthesize_segment(doc, seg)
        done.append(seg.index)
    progress(100, f"Generated {len(done)} segment(s).")
    return done


def regenerate(doc: AudioDocument, segments: Iterable[Segment], progress: Optional[Progress] = None,
               cancel: Callable[[], bool] = lambda: False) -> List[int]:
    """New take for the chosen segments (the previous take file is kept until cleanup)."""
    segs = list(segments)
    for seg in segs:
        key = segment_key(doc, seg)
        doc.takes[key] = doc.takes.get(key, 0) + 1
    return generate(doc, segs, progress, cancel)


# ------------------------------------------------------------------ assembly
@dataclass
class TimelineItem:
    index: int
    start: float
    end: float
    emotion: str
    text: str


def assemble(doc: AudioDocument, require_all: bool = True) -> Tuple[np.ndarray, int, List[TimelineItem]]:
    """Join segment audio with sentence/paragraph gaps and [pause] tags. Mono float32."""
    import soundfile as sf
    pr = doc.parsed()
    if not pr.segments:
        raise AudioStudioError("There is no text to speak.")
    missing = [s.index + 1 for s in pr.segments if not segment_ready(doc, s)]
    if missing and require_all:
        raise AudioStudioError(f"Segments not generated yet: {missing[:10]}")
    parts, timeline, sr, t = [], [], None, 0.0
    prev_par = None
    for seg in pr.segments:
        if not segment_ready(doc, seg):
            continue
        audio, rate = sf.read(str(segment_path(doc, seg)), dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr is None:
            sr = rate
        elif rate != sr:
            audio = _resample(audio, rate, sr)
        gap = 0.0 if prev_par is None else (doc.settings.paragraph_gap if seg.paragraph != prev_par
                                            else doc.settings.sentence_gap)
        gap += seg.pause_before
        if gap > 0:
            parts.append(np.zeros(int(round(gap * sr)), dtype=np.float32))
            t += gap
        dur = len(audio) / sr
        timeline.append(TimelineItem(seg.index, round(t, 3), round(t + dur, 3), seg.emotion, seg.text))
        parts.append(audio.astype(np.float32))
        t += dur
        prev_par = seg.paragraph
    if pr.trailing_pause and sr:
        parts.append(np.zeros(int(round(pr.trailing_pause * sr)), dtype=np.float32))
    if not parts:
        raise AudioStudioError("No generated audio to assemble.")
    return np.concatenate(parts), int(sr), timeline


def _resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    n = int(round(len(audio) * dst / src))
    return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)


def write_master(doc: AudioDocument, require_all: bool = True) -> Tuple[Path, List[TimelineItem]]:
    import soundfile as sf
    audio, sr, timeline = assemble(doc, require_all)
    out = doc.cache / "master.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), audio, sr, subtype="FLOAT")
    return out, timeline


def segment_preview(doc: AudioDocument, seg: Segment) -> Path:
    """Path of one segment's audio (generating it if needed)."""
    return synthesize_segment(doc, seg)


def peaks(audio: np.ndarray, bins: int = 800) -> np.ndarray:
    """Max-abs envelope for drawing a waveform."""
    if audio.size == 0:
        return np.zeros(bins, dtype=np.float32)
    bins = max(1, min(bins, audio.size))
    edges = np.linspace(0, audio.size, bins + 1).astype(int)
    return np.array([np.abs(audio[a:b]).max() if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])],
                    dtype=np.float32)


# ------------------------------------------------------------------ export
@dataclass(frozen=True)
class ExportFormat:
    key: str
    label: str
    ext: str
    encoder: str
    qualities: Tuple[Tuple[str, List[str]], ...]     # (label, ffmpeg args)
    rates: Tuple[int, ...] = (22050, 24000, 32000, 44100, 48000)


FORMATS: List[ExportFormat] = [
    ExportFormat("wav", "WAV (uncompressed)", "wav", "pcm_s16le",
                 (("16-bit PCM", ["-c:a", "pcm_s16le"]), ("24-bit PCM", ["-c:a", "pcm_s24le"]))),
    ExportFormat("flac", "FLAC (lossless)", "flac", "flac",
                 (("16-bit", ["-c:a", "flac", "-sample_fmt", "s16"]), ("24-bit", ["-c:a", "flac", "-sample_fmt", "s32"]))),
    ExportFormat("mp3", "MP3", "mp3", "libmp3lame",
                 tuple((f"{b} kbps", ["-c:a", "libmp3lame", "-b:a", f"{b}k"]) for b in (320, 256, 192, 128, 96))
                 + (("VBR high (V2)", ["-c:a", "libmp3lame", "-q:a", "2"]),)),
    ExportFormat("m4a", "M4A (AAC)", "m4a", "aac",
                 tuple((f"{b} kbps", ["-c:a", "aac", "-b:a", f"{b}k"]) for b in (256, 192, 128, 96))),
    ExportFormat("ogg", "Ogg Vorbis", "ogg", "libvorbis",
                 tuple((f"Quality {q}", ["-c:a", "libvorbis", "-q:a", str(q)]) for q in (8, 6, 4))),
    ExportFormat("opus", "Opus", "opus", "libopus",
                 tuple((f"{b} kbps", ["-c:a", "libopus", "-b:a", f"{b}k"]) for b in (128, 96, 64, 32)),
                 rates=(48000, 24000, 16000)),
    ExportFormat("alac", "Apple Lossless (ALAC, .m4a)", "m4a", "alac", (("Lossless", ["-c:a", "alac"]),)),
]


@lru_cache(maxsize=4)
def _encoders(ff: str) -> frozenset:
    try:
        out = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30,
                             **no_window_kwargs()).stdout
    except Exception:
        return frozenset()
    return frozenset(m.group(1) for m in re.finditer(r"^\s*A\S*\s+(\S+)", out, re.M))


def available_formats() -> List[ExportFormat]:
    from src.backend.video.pipeline import ffmpeg_path
    ff = ffmpeg_path()
    if not ff:
        return [f for f in FORMATS if f.key == "wav"]           # soundfile fallback
    enc = _encoders(ff)
    return [f for f in FORMATS if f.encoder in enc]


def get_format(key: str) -> ExportFormat:
    for f in FORMATS:
        if f.key == key:
            return f
    raise AudioStudioError(f"Unknown export format '{key}'.")


def export(doc: AudioDocument, fmt: str, quality: int = 0, sample_rate: int = 44100, channels: int = 1,
           normalize: bool = True, out_path: Optional[Path] = None) -> Path:
    """Assemble all segments and encode. `quality` indexes ExportFormat.qualities."""
    from src.backend.video.pipeline import ffmpeg_path
    f = get_format(fmt)
    if f.key not in {x.key for x in available_formats()}:
        raise AudioStudioError(f"{f.label} is not supported by the installed ffmpeg.")
    if sample_rate not in f.rates:
        raise AudioStudioError(f"{f.label} supports sample rates {', '.join(map(str, f.rates))} Hz.")
    master, _ = write_master(doc)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(out_path) if out_path else doc.exports / f"{doc.doc_id}_{stamp}.{f.ext}"
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = ffmpeg_path()
    af = ["loudnorm=I=-16:TP=-1.5:LRA=11"] if normalize else []
    af.append(f"aresample={sample_rate}")
    cmd = [ff, "-y", "-loglevel", "error", "-i", str(master), "-af", ",".join(af), "-ar", str(sample_rate),
           "-ac", str(channels)] + list(f.qualities[min(max(quality, 0), len(f.qualities) - 1)][1])
    if f.ext == "m4a":
        cmd += ["-movflags", "+faststart"]
    cmd += ["-metadata", f"title={doc.name}", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, **no_window_kwargs())
    if proc.returncode != 0:
        raise AudioStudioError(f"Export failed: {proc.stderr.strip()[-600:]}")
    return out
