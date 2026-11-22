"""Piper voice engine (user-imported `.onnx` + `.onnx.json`), run directly with ONNX Runtime.

No `piper-tts` package is needed: text -> espeak-ng phonemes (phonemizer + espeakng-loader, the same
front-end Kokoro uses) -> the voice's own `phoneme_id_map` -> VITS ONNX model -> 16-bit audio.
Only `phoneme_type: espeak` voices are supported (nearly all published Piper voices).
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.backend.tts.base import Capabilities, Speaker, TTSEngine

PAD, BOS, EOS = "_", "^", "$"
SENTENCE_GAP = 0.25          # seconds of silence between sentences

try:                         # share kokoro-onnx's lock: espeak-ng has process-global state
    from kokoro_onnx.tokenizer import _espeak_lock as _ESPEAK_LOCK
except Exception:            # pragma: no cover - kokoro-onnx not installed
    _ESPEAK_LOCK = threading.Lock()


def read_config(config_path: Path) -> Dict:
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def check_runtime() -> Tuple[bool, str]:
    """Are the Python packages this engine needs importable?"""
    missing = []
    for mod, pkg in (("onnxruntime", "onnxruntime"), ("phonemizer", "phonemizer"),
                     ("espeakng_loader", "espeakng-loader")):
        try:
            __import__(mod)
        except Exception:
            missing.append(pkg)
    if missing:
        return False, f"Missing Python packages: {', '.join(missing)} (pip install {' '.join(missing)})."
    return True, ""


def _setup_espeak() -> None:
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper
    with _ESPEAK_LOCK:
        EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
        EspeakWrapper.set_library(espeakng_loader.get_library_path())


def split_sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def phonemes_to_ids(phonemes: str, id_map: Dict[str, List[int]], phoneme_map: Optional[Dict] = None) -> List[int]:
    """Piper's encoding: BOS PAD (phoneme PAD)* EOS; unknown phonemes are skipped."""
    ids = list(id_map[BOS]) + list(id_map.get(PAD, []))
    for ph in phonemes:
        for p in (phoneme_map or {}).get(ph, [ph]):
            if p in id_map:
                ids += id_map[p] + id_map.get(PAD, [])
    return ids + list(id_map[EOS])


class PiperEngine(TTSEngine):
    capabilities = Capabilities(speed_range=(0.5, 2.0), pauses=False, pronunciation=True, emphasis=False)
    custom = True

    def __init__(self, model_path: Path, config_path: Path, engine_id: str, name: str,
                 license_summary: str = ""):
        super().__init__()
        self.model_path, self.config_path = Path(model_path), Path(config_path)
        self.id, self.name = engine_id, name
        self.description = f"Piper voice imported from {self.model_path.name}. Runs offline with ONNX Runtime."
        self.license_summary = license_summary or "See the voice's model card / licence file (not bundled)."
        self._session = None
        self._cfg: Optional[Dict] = None
        try:
            self.sample_rate = int(self.config.get("audio", {}).get("sample_rate", 22050))
        except Exception:
            self.sample_rate = 22050

    @property
    def config(self) -> Dict:
        if self._cfg is None:
            self._cfg = read_config(self.config_path)
        return self._cfg

    def is_installed(self) -> Tuple[bool, str]:
        for p in (self.model_path, self.config_path):
            if not p.is_file():
                return False, f"Model file missing: {p}. Re-import the model or restore the file."
        try:
            cfg = self.config
        except Exception as exc:
            return False, f"Unreadable voice config {self.config_path.name}: {exc}"
        if cfg.get("phoneme_type", "espeak") != "espeak":
            return False, f"Unsupported Piper phoneme type '{cfg.get('phoneme_type')}' (only 'espeak' voices)."
        return check_runtime()

    def _load(self) -> None:
        import onnxruntime as ort
        _setup_espeak()
        opts = ort.SessionOptions()
        self._session = ort.InferenceSession(str(self.model_path), sess_options=opts,
                                             providers=["CPUExecutionProvider"])

    # ---- voices
    def speakers(self) -> List[Speaker]:
        try:
            cfg = self.config
        except Exception:
            return []
        lang = cfg.get("language", {}) or {}
        language = lang.get("name_english", "") or cfg.get("espeak", {}).get("voice", "")
        if lang.get("country_english"):
            language = f"{language} ({lang['country_english']})"
        smap = cfg.get("speaker_id_map") or {}
        n = int(cfg.get("num_speakers", 1) or 1)
        base = self.model_path.name.replace(".onnx", "")
        if smap:
            return [Speaker(str(k), f"{k} (#{v})", language, "", base) for k, v in sorted(smap.items(), key=lambda kv: kv[1])]
        if n > 1:
            return [Speaker(str(i), f"Speaker {i}", language, "", base) for i in range(n)]
        return [Speaker("default", base, language, "", "single-speaker voice", True)]

    def _speaker_index(self, speaker: str) -> Optional[int]:
        cfg = self.config
        if int(cfg.get("num_speakers", 1) or 1) <= 1:
            return None
        smap = cfg.get("speaker_id_map") or {}
        if speaker in smap:
            return int(smap[speaker])
        return int(speaker) if str(speaker).isdigit() else 0

    # ---- synthesis
    def phonemize(self, text: str) -> str:
        import phonemizer
        voice = self.config.get("espeak", {}).get("voice", "en-us")
        with _ESPEAK_LOCK:
            return phonemizer.phonemize(text, language=voice, backend="espeak",
                                        preserve_punctuation=True, with_stress=True).strip()

    def _synthesize(self, text, speaker, speed, sentence_pause, clause_pause):
        cfg = self.config
        inf = cfg.get("inference", {})
        scales = np.array([inf.get("noise_scale", 0.667), float(inf.get("length_scale", 1.0)) / max(speed, 0.1),
                           inf.get("noise_w", 0.8)], dtype=np.float32)
        sid = self._speaker_index(speaker)
        names = {i.name for i in self._session.get_inputs()}
        gap = np.zeros(int(self.sample_rate * SENTENCE_GAP), dtype=np.float32)
        parts: List[np.ndarray] = []
        for sentence in split_sentences(text) or [text]:
            ids = phonemes_to_ids(self.phonemize(sentence), cfg["phoneme_id_map"], cfg.get("phoneme_map"))
            if len(ids) <= 3:
                continue
            feed = {"input": np.array([ids], dtype=np.int64),
                    "input_lengths": np.array([len(ids)], dtype=np.int64),
                    "scales": scales}
            if "sid" in names:
                feed["sid"] = np.array([sid or 0], dtype=np.int64)
            audio = self._session.run(None, feed)[0]
            parts += [np.asarray(audio, dtype=np.float32).reshape(-1), gap]
        if not parts:
            return np.zeros(int(self.sample_rate * 0.1), dtype=np.float32), self.sample_rate
        audio = np.concatenate(parts[:-1])
        peak = float(np.max(np.abs(audio))) or 1.0
        if peak > 1.0:                      # Piper outputs roughly [-1, 1]; guard against clipping
            audio = audio / peak
        return audio, self.sample_rate
