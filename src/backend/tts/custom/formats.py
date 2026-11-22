"""Model-format adapters for user-imported TTS models.

Each `ModelFormat` knows how to recognise its files, check runtime dependencies and build a `TTSEngine`.
To support a new format later: write `detect`, `check_deps` and `create` functions and call `register()`.
Formats that are recognised but cannot run are reported by `UNSUPPORTED` rules with setup advice.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.backend.tts.base import TTSEngine

MAX_SCAN = 200          # files inspected per folder (folders are scanned one level deep)


@dataclass
class Detection:
    """Result of inspecting a file/folder. `ok` means it can be imported and run."""
    ok: bool
    format: str = ""
    format_label: str = ""
    files: Dict[str, str] = field(default_factory=dict)     # role -> absolute path
    suggested_name: str = ""
    speakers: int = 0
    message: str = ""                                       # what was found / what is wrong
    instructions: str = ""                                  # how to fix or set up
    deps_ok: bool = True
    deps_message: str = ""

    @property
    def size_bytes(self) -> int:
        return sum(Path(p).stat().st_size for p in self.files.values() if Path(p).is_file())


@dataclass(frozen=True)
class ModelFormat:
    key: str
    label: str
    detect: Callable[[Path], List[Detection]]            # path (file or folder) -> candidates
    check_deps: Callable[[], Tuple[bool, str]]
    create: Callable[[Dict], TTSEngine]                   # store entry -> engine
    setup_help: str = ""


FORMATS: Dict[str, ModelFormat] = {}


def register(fmt: ModelFormat) -> None:
    FORMATS[fmt.key] = fmt


# ------------------------------------------------------------------ helpers
def _files(path: Path) -> List[Path]:
    """The file itself, or the files of a folder and its direct subfolders."""
    if path.is_file():
        return [path]
    out: List[Path] = []
    for p in sorted(path.iterdir()) if path.is_dir() else []:
        if p.is_file():
            out.append(p)
        elif p.is_dir() and not p.name.startswith("."):
            out += sorted(q for q in p.iterdir() if q.is_file())
        if len(out) >= MAX_SCAN:
            break
    return out


def _siblings(path: Path) -> List[Path]:
    """Files to search for companions: the folder's files, or the file's own folder."""
    return _files(path if path.is_dir() else path.parent)


def onnx_inputs(path: Path) -> List[str]:
    try:
        import onnxruntime as ort
        return [i.name for i in ort.InferenceSession(str(path), providers=["CPUExecutionProvider"]).get_inputs()]
    except Exception:
        return []


def _pretty(stem: str) -> str:
    return stem.replace("_", " ").replace("-", " ").strip().title() or "Custom voice"


# ------------------------------------------------------------------ Piper
def _piper_detect(path: Path) -> List[Detection]:
    from src.backend.tts.piper_engine import check_runtime
    cands = _siblings(path)
    if path.is_file():                       # only the chosen pair when a single file was picked
        if path.name.endswith(".onnx.json"):
            cands = [path, path.with_name(path.name[:-5])]
        elif path.suffix == ".onnx":
            cands = [path, path.with_name(path.name + ".json")]
        else:
            return []
    out = []
    for onnx in [p for p in cands if p.suffix == ".onnx" and p.is_file()]:
        cfg_path = onnx.with_name(onnx.name + ".json")
        if not cfg_path.is_file():
            alt = onnx.parent / "config.json"
            cfg_path = alt if alt.is_file() else cfg_path
        if not cfg_path.is_file():
            continue
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "phoneme_id_map" not in cfg:
            continue
        ok_deps, why = check_runtime()
        n = int(cfg.get("num_speakers", 1) or 1)
        if cfg.get("phoneme_type", "espeak") != "espeak":
            out.append(Detection(False, "piper", "Piper voice", {"model": str(onnx), "config": str(cfg_path)},
                                 _pretty(onnx.stem), n,
                                 f"Piper voice uses phoneme type '{cfg.get('phoneme_type')}', which is not supported.",
                                 "Choose a Piper voice with \"phoneme_type\": \"espeak\" (almost all published voices)."))
            continue
        out.append(Detection(True, "piper", "Piper voice (ONNX)", {"model": str(onnx), "config": str(cfg_path)},
                             _pretty(onnx.stem), n,
                             f"Piper voice · {cfg.get('language', {}).get('name_english', cfg.get('espeak', {}).get('voice', '?'))}"
                             f" · {cfg.get('audio', {}).get('sample_rate', '?')} Hz · {n} speaker(s)",
                             "" if ok_deps else why, ok_deps, why))
    return out


def _piper_create(entry: Dict) -> TTSEngine:
    from src.backend.tts.piper_engine import PiperEngine
    f = entry["files"]
    return PiperEngine(Path(f["model"]), Path(f["config"]), entry["id"], entry["name"], entry.get("license", ""))


def _piper_deps():
    from src.backend.tts.piper_engine import check_runtime
    return check_runtime()


# ------------------------------------------------------------------ Kokoro-compatible
def _is_voices(p: Path) -> bool:
    return p.suffix in (".bin", ".npz") and ("voice" in p.name.lower() or p.suffix == ".npz")


def _kokoro_detect(path: Path) -> List[Detection]:
    files = _siblings(path)
    voices = [p for p in files if _is_voices(p)]
    onnxs = [p for p in files if p.suffix == ".onnx" and not p.with_name(p.name + ".json").is_file()]
    if path.is_file():
        if path.suffix == ".onnx":
            onnxs = [path] if path in onnxs or not path.with_name(path.name + ".json").is_file() else []
        elif _is_voices(path):
            voices = [path]
        else:
            return []
    if not onnxs or not voices:
        return []
    ok_deps, why = _kokoro_deps()
    out = []
    for onnx in onnxs:
        inputs = onnx_inputs(onnx) if ok_deps else []
        if inputs and "style" not in inputs:
            continue                                   # some other ONNX model
        vfile = voices[0]
        n = 0
        try:
            import numpy as np
            with np.load(vfile) as d:
                n = len(d.files)
        except Exception:
            out.append(Detection(False, "kokoro", "Kokoro-compatible (ONNX)", {"model": str(onnx), "voices": str(vfile)},
                                 _pretty(onnx.stem), 0, f"Could not read voices file {vfile.name}.",
                                 "Kokoro voices must be a NumPy archive (.bin/.npz) such as voices-v1.0.bin."))
            continue
        out.append(Detection(True, "kokoro", "Kokoro-compatible (ONNX)", {"model": str(onnx), "voices": str(vfile)},
                             _pretty(onnx.stem), n, f"Kokoro ONNX model + {vfile.name} · {n} voices",
                             "" if ok_deps else why, ok_deps, why))
    return out


def _kokoro_deps() -> Tuple[bool, str]:
    try:
        import kokoro_onnx  # noqa: F401
        return True, ""
    except Exception:
        return False, "Python package 'kokoro-onnx' is not installed (pip install kokoro-onnx soundfile)."


def _kokoro_create(entry: Dict) -> TTSEngine:
    from src.backend.tts.kokoro_engine import KokoroEngine
    f = entry["files"]
    model, voices = Path(f["model"]), Path(f["voices"])
    eng = KokoroEngine(model.parent, model.name, str(voices),          # absolute path is kept as-is
                       engine_id=entry["id"], name=entry["name"],
                       description=f"Kokoro-compatible model imported from {model.name}. Runs offline.",
                       license_summary=entry.get("license", "") or "See the model's licence (imported by you).")
    eng.custom = True
    return eng


register(ModelFormat("piper", "Piper voice (.onnx + .onnx.json)", _piper_detect, _piper_deps, _piper_create,
                     "Download a voice's .onnx and matching .onnx.json from the Piper voices collection, "
                     "keep them in the same folder, then import either file or the folder."))
register(ModelFormat("kokoro", "Kokoro-compatible ONNX (.onnx + voices .bin)", _kokoro_detect, _kokoro_deps,
                     _kokoro_create,
                     "Put the Kokoro .onnx model (e.g. kokoro-v1.0.int8.onnx) and its voices file "
                     "(voices-v1.0.bin) in one folder and import the folder."))


# ------------------------------------------------------------------ recognised but unsupported
UNSUPPORTED: List[Tuple[Callable[[List[Path]], bool], str, str]] = [
    (lambda fs: any(f.name == "tokens.txt" for f in fs) and any(f.suffix == ".onnx" for f in fs),
     "This looks like a sherpa-onnx model (tokens.txt + .onnx).",
     "sherpa-onnx models are not supported yet. Use the Piper (.onnx + .onnx.json) or Kokoro ONNX build of the "
     "voice if one exists."),
    (lambda fs: any(f.suffix in (".pth", ".pt", ".ckpt") for f in fs),
     "This looks like a PyTorch checkpoint (.pth/.pt/.ckpt), e.g. Coqui TTS / XTTS / StyleTTS.",
     "PyTorch checkpoints need their project's own Python runtime and cannot be loaded directly. Export the model "
     "to ONNX in Piper or Kokoro format, or use an existing ONNX build of the voice."),
    (lambda fs: any(f.suffix == ".safetensors" for f in fs),
     "This looks like a Hugging Face model (.safetensors), e.g. the original PyTorch Kokoro, Parler-TTS or Bark.",
     "Hugging Face PyTorch models are not supported directly. For Kokoro, import the ONNX build "
     "(kokoro-*.onnx + voices-*.bin)."),
    (lambda fs: any(f.suffix == ".gguf" for f in fs),
     "This looks like a GGUF model.",
     "GGUF speech models are not supported. Use an ONNX build in Piper or Kokoro format."),
    (lambda fs: any(f.suffix == ".onnx" for f in fs),
     "An ONNX file was found, but it is not a Piper voice or a Kokoro model.",
     "Piper voices need the matching .onnx.json next to the .onnx file. Kokoro models need a voices file "
     "(voices-*.bin) in the same folder. Other ONNX TTS architectures are not supported yet."),
]


def detect(path: str | Path) -> List[Detection]:
    """All importable candidates at `path`; if none, a single failed Detection explaining why."""
    path = Path(path).expanduser()
    if not path.exists():
        return [Detection(False, message=f"Not found: {path}")]
    found: List[Detection] = []
    for fmt in FORMATS.values():
        try:
            found += fmt.detect(path)
        except Exception as exc:          # a broken adapter must not hide the others
            found.append(Detection(False, fmt.key, fmt.label, message=f"{fmt.label}: could not inspect ({exc})."))
    seen, uniq = set(), []
    for d in found:
        k = tuple(sorted(d.files.values()))
        if k not in seen:
            seen.add(k); uniq.append(d)
    if uniq:
        return uniq
    files = _files(path)
    for test, what, how in UNSUPPORTED:
        if test(files):
            return [Detection(False, message=what, instructions=how + "\n\n" + supported_formats_help())]
    return [Detection(False, message="No supported TTS model files were found here.",
                      instructions=supported_formats_help())]


def supported_formats_help() -> str:
    return "Supported formats:\n" + "\n".join(f"• {f.label}: {f.setup_help}" for f in FORMATS.values())
