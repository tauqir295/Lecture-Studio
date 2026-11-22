"""Kokoro-82M (ONNX) local TTS engine — the default narration engine.

Runtime:  kokoro-onnx (MIT) + onnxruntime (MIT) + espeak-ng via espeakng-loader/phonemizer (GPL-3.0).
Weights:  Kokoro-82M by hexgrad, Apache-2.0 (ONNX export from the kokoro-onnx project).
Files:    <models_root>/tts/kokoro-82m/kokoro-v1.0.onnx and voices-v1.0.bin
"""
from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import numpy as np

from src.backend.tts.base import Capabilities, Speaker, TTSEngine

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/"
FILES = {
    "kokoro-v1.0.onnx": "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}

# Voice-id prefix: first letter = language, second = gender (as published by the model author).
LANG = {"a": ("English (US)", "en-us"), "b": ("English (UK)", "en-gb"), "e": ("Spanish", "es"),
        "f": ("French", "fr-fr"), "h": ("Hindi", "hi"), "i": ("Italian", "it"),
        "j": ("Japanese", "ja"), "p": ("Portuguese (BR)", "pt-br"), "z": ("Mandarin", "cmn")}
GENDER = {"f": "female voice", "m": "male voice"}
# Notes for well-known English voices (subjective; based on listening and the model author's voice list).
STYLE = {
    "af_heart": "warm, natural · best overall", "af_bella": "bright, expressive",
    "af_nicole": "soft, close-mic", "af_sarah": "clear, neutral", "af_sky": "light, young",
    "am_michael": "calm, steady narrator", "am_fenrir": "deep, confident", "am_puck": "lively",
    "am_adam": "plain", "bf_emma": "clear British narrator", "bf_isabella": "gentle British",
    "bm_george": "mature British narrator", "bm_fable": "storyteller British", "bm_lewis": "deep British",
}
RECOMMENDED = {"af_heart", "af_bella", "am_michael", "am_fenrir", "bf_emma", "bm_george"}


class KokoroEngine(TTSEngine):
    id = "kokoro-82m"
    name = "Kokoro-82M (local, default)"
    description = "82M-parameter neural TTS. Natural English narration, runs offline on CPU via ONNX Runtime."
    license_summary = ("Weights: Apache-2.0 (hexgrad/Kokoro-82M). kokoro-onnx & onnxruntime: MIT. "
                       "espeak-ng / phonemizer (pronunciation front-end): GPL-3.0.")
    capabilities = Capabilities(speed_range=(0.5, 2.0), pauses=True, pronunciation=True, emphasis=False)
    sample_rate = 24000

    def __init__(self, model_dir: Path, model_file: str = "kokoro-v1.0.onnx", voices_file: str = "voices-v1.0.bin",
                 engine_id: Optional[str] = None, name: Optional[str] = None, description: Optional[str] = None,
                 license_summary: Optional[str] = None):
        """Defaults describe the bundled Kokoro-82M. Custom Kokoro-compatible models (other ONNX builds,
        e.g. int8/fp16, or other voice packs) pass their own files, id and name."""
        super().__init__()
        self.model_dir = Path(model_dir)
        self.model_file, self.voices_file = model_file, voices_file
        if engine_id:
            self.id = engine_id
        if name:
            self.name = name
        if description:
            self.description = description
        if license_summary is not None:
            self.license_summary = license_summary
        self._kokoro = None
        self._voice_ids: Optional[List[str]] = None

    @property
    def downloadable(self) -> bool:
        return self.is_default_model

    @property
    def is_default_model(self) -> bool:
        return self.id == KokoroEngine.id

    @property
    def model_path(self) -> Path:
        return self.model_dir / self.model_file

    @property
    def voices_path(self) -> Path:
        return self.model_dir / self.voices_file

    def is_installed(self) -> Tuple[bool, str]:
        try:
            import kokoro_onnx  # noqa: F401
        except Exception:
            return False, "Python package 'kokoro-onnx' is not installed (pip install kokoro-onnx soundfile)."
        missing = [p.name for p in (self.model_path, self.voices_path) if not p.is_file()]
        if missing:
            hint = " Use 'Download model'." if self.is_default_model else " Re-import the model or restore the files."
            return False, f"Model files missing in {self.model_dir}: {', '.join(missing)}.{hint}"
        return True, ""

    def _load(self) -> None:
        from kokoro_onnx import Kokoro
        self._kokoro = Kokoro(str(self.model_path), str(self.voices_path))
        self._voice_ids = sorted(self._kokoro.get_voices())

    def speakers(self) -> List[Speaker]:
        ids = self._voice_ids
        if ids is None:
            if not self.voices_path.is_file():
                return []
            try:  # voices file is a numpy archive; read names without loading the model
                with np.load(self.voices_path) as data:
                    ids = sorted(data.files)
            except Exception:
                return []
        out = []
        for vid in ids:
            lang = LANG.get(vid[:1], ("", ""))[0]
            gender = GENDER.get(vid[1:2], "")
            name = vid.split("_", 1)[-1].capitalize()
            out.append(Speaker(vid, f"{name} ({vid})", lang, gender, STYLE.get(vid, ""), vid in RECOMMENDED))
        # English first, recommended first
        return sorted(out, key=lambda s: (not s.is_english, not s.recommended, s.id))

    def default_speaker(self) -> str:
        if self.find_speaker("af_heart"):
            return "af_heart"
        return super().default_speaker()

    def _synthesize(self, text, speaker, speed, sentence_pause, clause_pause):
        lang = LANG.get(speaker[:1], ("", "en-us"))[1]
        audio, sr = self._kokoro.create(text, voice=speaker, speed=float(speed), lang=lang,
                                        sentence_pause=float(sentence_pause), clause_pause=float(clause_pause))
        return np.asarray(audio, dtype=np.float32), int(sr)

    # ---- installation
    def download(self, progress: Optional[Callable[[int, str], None]] = None,
                 cancel: Callable[[], bool] = lambda: False) -> None:
        """Download and checksum-verify the model files (one-time, needs internet). Default model only."""
        if not self.is_default_model:
            raise RuntimeError("Custom models are imported from local files, not downloaded.")
        self.model_dir.mkdir(parents=True, exist_ok=True)
        for i, (fname, sha) in enumerate(FILES.items()):
            dest = self.model_dir / fname
            if dest.is_file() and _sha256(dest) == sha:
                continue
            part = dest.with_suffix(dest.suffix + ".part")
            h = hashlib.sha256()
            with urllib.request.urlopen(RELEASE + fname, timeout=60) as r, open(part, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while chunk := r.read(1 << 20):
                    if cancel():
                        raise RuntimeError("Download cancelled.")
                    f.write(chunk); h.update(chunk); done += len(chunk)
                    if progress and total:
                        progress(int((i + done / total) / len(FILES) * 100), f"Downloading {fname}…")
            if h.hexdigest() != sha:
                part.unlink(missing_ok=True)
                raise RuntimeError(f"Checksum mismatch for {fname}; download aborted.")
            part.replace(dest)
        self._state = None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()
