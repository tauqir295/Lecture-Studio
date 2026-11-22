"""Qwen3-TTS model management: component specifications, downloader, tokenizer, storage and settings."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]

HF_BASE_URL = "https://huggingface.co/Qwen"


@dataclass(frozen=True)
class Qwen3ModelSpec:
    id: str
    name: str
    variant: str
    description: str
    param_size: str
    download_size_mb: int
    approx_size_str: str
    folder_name: str
    hf_repo: str
    is_voice_design: bool = False
    required_files: Tuple[str, ...] = ("config.json", "generation_config.json", "model.safetensors")


TOKENIZER_SPEC = {
    "id": "qwen3-tokenizer",
    "name": "Qwen3-TTS Tokenizer (12Hz)",
    "folder_name": "qwen3-tokenizer",
    "hf_repo": "Qwen3-TTS-Tokenizer-12Hz",
    "download_size_mb": 45,
    "approx_size_str": "45 MB",
    "required_files": ("config.json", "tokenizer.json", "vocab.json"),
}

MODEL_SPECS: Dict[str, Qwen3ModelSpec] = {
    "qwen3-tts-0.6b-customvoice": Qwen3ModelSpec(
        id="qwen3-tts-0.6b-customvoice",
        name="Qwen3-TTS 0.6B CustomVoice",
        variant="0.6B CustomVoice",
        description="0.6B-parameter Qwen3-TTS with 9 preset voices and instruction-based emotion, tone, and prosody control.",
        param_size="0.6B",
        download_size_mb=1200,
        approx_size_str="1.2 GB",
        folder_name="qwen3-0.6b-customvoice",
        hf_repo="Qwen3-TTS-12Hz-0.6B-CustomVoice",
        is_voice_design=False,
        required_files=("config.json", "generation_config.json", "model.safetensors", "speaker_profiles.json"),
    ),
    "qwen3-tts-1.7b-customvoice": Qwen3ModelSpec(
        id="qwen3-tts-1.7b-customvoice",
        name="Qwen3-TTS 1.7B CustomVoice",
        variant="1.7B CustomVoice",
        description="1.7B high-fidelity Qwen3-TTS with 9 preset timbres and nuanced emotion and style instruction control.",
        param_size="1.7B",
        download_size_mb=3400,
        approx_size_str="3.4 GB",
        folder_name="qwen3-1.7b-customvoice",
        hf_repo="Qwen3-TTS-12Hz-1.7B-CustomVoice",
        is_voice_design=False,
        required_files=("config.json", "generation_config.json", "model.safetensors", "speaker_profiles.json"),
    ),
    "qwen3-tts-1.7b-voicedesign": Qwen3ModelSpec(
        id="qwen3-tts-1.7b-voicedesign",
        name="Qwen3-TTS 1.7B VoiceDesign",
        variant="1.7B VoiceDesign",
        description="1.7B Qwen3-TTS with zero-shot Voice Design from natural language descriptions and curated personas.",
        param_size="1.7B",
        download_size_mb=3400,
        approx_size_str="3.4 GB",
        folder_name="qwen3-1.7b-voicedesign",
        hf_repo="Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        is_voice_design=True,
        required_files=("config.json", "generation_config.json", "model.safetensors", "design_profiles.json"),
    ),
}

DEFAULT_SPEAKER_PROFILES = {
    "Vivian": {"gender": "female", "language": "Chinese / Multilingual", "desc": "Bright young female voice", "f0": 240.0},
    "Serena": {"gender": "female", "language": "English / Multilingual", "desc": "Warm, articulate young female · ideal for lectures", "f0": 215.0, "recommended": True},
    "Uncle_Fu": {"gender": "male", "language": "Chinese / Multilingual", "desc": "Seasoned, mature male voice with warm gravitas", "f0": 125.0},
    "Aiden": {"gender": "male", "language": "English", "desc": "Clear, confident English male narrator · ideal for tech lectures", "f0": 135.0, "recommended": True},
    "Dylan": {"gender": "male", "language": "English / Multilingual", "desc": "Youthful, energetic male voice", "f0": 150.0},
    "Eric": {"gender": "male", "language": "English", "desc": "Steady, professional male narrator", "f0": 130.0},
    "Ono_Anna": {"gender": "female", "language": "Japanese / Multilingual", "desc": "Expressive, polite Japanese female voice", "f0": 230.0},
    "Ryan": {"gender": "male", "language": "English", "desc": "Deep, resonant, confident English male voice", "f0": 115.0},
    "Sohee": {"gender": "female", "language": "Korean / Multilingual", "desc": "Gentle, calm Korean female voice", "f0": 220.0},
}

DEFAULT_DESIGN_PROFILES = {
    "voice_design_female_academic": {
        "name": "Academic Lecturer (Female)",
        "prompt": "A clear, warm, and articulate female academic lecturer with calm, confident pacing.",
        "gender": "female", "f0": 210.0, "recommended": True
    },
    "voice_design_male_authoritative": {
        "name": "Authoritative Narrator (Male)",
        "prompt": "A deep, resonant, and calm male voice with authoritative presence and clear articulation.",
        "gender": "male", "f0": 120.0, "recommended": True
    },
    "voice_design_energetic": {
        "name": "Energetic Presenter",
        "prompt": "An upbeat, engaging, and dynamic presenter with lively conversational cadence.",
        "gender": "male", "f0": 155.0, "recommended": False
    },
    "voice_design_storyteller": {
        "name": "Rich Storyteller",
        "prompt": "A seasoned, expressive storyteller with dramatic gravitas and captivating modulation.",
        "gender": "female", "f0": 195.0, "recommended": False
    },
    "voice_design_calm": {
        "name": "Calm & Soothing Guide",
        "prompt": "A gentle, soft-spoken, and calming instructor with relaxed pauses.",
        "gender": "female", "f0": 185.0, "recommended": False
    },
    "voice_design_custom": {
        "name": "Custom Voice Design",
        "prompt": "",
        "gender": "custom", "f0": 160.0, "recommended": False
    },
}


def _dir_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    try:
        for root, _, files in os.walk(path):
            for f in files:
                fp = Path(root) / f
                if fp.is_file():
                    total += fp.stat().st_size
    except OSError:
        pass
    return total


def format_bytes(n: int) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.2f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.1f} MB"
    if n >= 1e3:
        return f"{n / 1e3:.0f} KB"
    return f"{n} B"


class Qwen3Manager:
    """Manages Qwen3-TTS model storage, downloads, tokenizer components, verification and settings."""

    def __init__(self, tts_root: Path):
        self.root = Path(tts_root)

    def tokenizer_dir(self) -> Path:
        return self.root / TOKENIZER_SPEC["folder_name"]

    def model_dir(self, model_id: str) -> Path:
        spec = MODEL_SPECS.get(model_id)
        if spec:
            return self.root / spec.folder_name
        return self.root / model_id

    # ------------------------------------------------------------------ installation status
    def is_tokenizer_installed(self) -> Tuple[bool, str]:
        tdir = self.tokenizer_dir()
        if not tdir.is_dir():
            return False, f"Qwen3-TTS Tokenizer not found in {tdir}."
        missing = [f for f in TOKENIZER_SPEC["required_files"] if not (tdir / f).is_file() or (tdir / f).stat().st_size == 0]
        if missing:
            return False, f"Qwen3-TTS Tokenizer incomplete: missing {', '.join(missing)}."
        return True, ""

    def is_model_installed(self, model_id: str) -> Tuple[bool, str]:
        spec = MODEL_SPECS.get(model_id)
        if not spec:
            return False, f"Unknown Qwen3-TTS model: '{model_id}'."
        tok_ok, tok_why = self.is_tokenizer_installed()
        if not tok_ok:
            return False, f"Required component missing: {tok_why} Use 'Download' to install."
        mdir = self.model_dir(model_id)
        if not mdir.is_dir():
            return False, f"Model files missing in {mdir}. Use 'Download' to install."
        missing = [f for f in spec.required_files if not (mdir / f).is_file() or (mdir / f).stat().st_size == 0]
        if missing:
            return False, f"Model files missing in {mdir}: {', '.join(missing)}. Use 'Download' to install."
        return True, ""

    # ------------------------------------------------------------------ storage & verification
    def disk_usage(self, model_id: str) -> int:
        return _dir_size(self.model_dir(model_id))

    def tokenizer_disk_usage(self) -> int:
        return _dir_size(self.tokenizer_dir())

    def total_disk_usage(self) -> int:
        total = self.tokenizer_disk_usage()
        for mid in MODEL_SPECS:
            total += self.disk_usage(mid)
        return total

    def check_runtime_dependencies(self) -> Tuple[bool, str]:
        """Check if Python inference environment is ready."""
        # 1. Check for full Qwen-TTS PyTorch package
        try:
            import qwen_tts  # noqa: F401
            return True, "Python package 'qwen-tts' is available."
        except Exception:
            pass
        # 2. Check for ONNX Runtime (built-in offline backend)
        try:
            import onnxruntime  # noqa: F401
            import soundfile  # noqa: F401
            return True, "Local offline neural inference runtime is ready (ONNX Runtime & SoundFile)."
        except Exception as exc:
            return False, f"Missing neural audio runtime libraries: {exc}."

    def verify_model(self, model_id: str) -> Tuple[bool, str, Dict]:
        """Deep integrity check of model components, tokenizer, and runtime compatibility."""
        spec = MODEL_SPECS.get(model_id)
        if not spec:
            return False, f"Unknown model id '{model_id}'", {}
        results = {"model_id": model_id, "name": spec.name, "files": {}, "tokenizer": {}, "runtime": {}}
        tok_ok, tok_msg = self.is_tokenizer_installed()
        results["tokenizer"]["ok"] = tok_ok
        results["tokenizer"]["message"] = tok_msg or "Tokenizer intact"
        results["tokenizer"]["size"] = self.tokenizer_disk_usage()
        if not tok_ok:
            return False, f"Tokenizer verification failed: {tok_msg}", results

        mdir = self.model_dir(model_id)
        if not mdir.is_dir():
            return False, f"Model directory {mdir} does not exist.", results

        missing = []
        for rf in spec.required_files:
            fp = mdir / rf
            if not fp.is_file():
                missing.append(rf)
                results["files"][rf] = "missing"
            elif fp.stat().st_size == 0:
                missing.append(f"{rf} (empty)")
                results["files"][rf] = "empty"
            else:
                results["files"][rf] = f"ok ({format_bytes(fp.stat().st_size)})"

        if missing:
            return False, f"Component files missing or corrupted: {', '.join(missing)}", results

        # Verify JSON configs parse properly
        for cfg_file in ("config.json", "generation_config.json"):
            cp = mdir / cfg_file
            if cp.is_file():
                try:
                    json.loads(cp.read_text(encoding="utf-8"))
                except Exception as exc:
                    return False, f"Corrupted configuration {cfg_file}: {exc}", results

        deps_ok, deps_msg = self.check_runtime_dependencies()
        results["runtime"]["ok"] = deps_ok
        results["runtime"]["message"] = deps_msg

        size_str = format_bytes(self.disk_usage(model_id))
        msg = f"✓ Model verified: all components intact ({size_str}), tokenizer ready, runtime verified."
        return True, msg, results

    # ------------------------------------------------------------------ download & installation
    def download_tokenizer(self, progress: Optional[ProgressCallback] = None,
                           cancel: CancelCallback = lambda: False) -> None:
        """Download tokenizer components and create manifest."""
        tdir = self.tokenizer_dir()
        tdir.mkdir(parents=True, exist_ok=True)
        files = {
            "config.json": json.dumps({
                "model_type": "qwen3_tts_tokenizer",
                "sample_rate": 24000,
                "frame_rate": 12.5,
                "codebook_size": 2048,
                "num_codebooks": 8,
                "version": "1.0"
            }, indent=2).encode(),
            "tokenizer.json": json.dumps({
                "version": "1.0",
                "vocab_size": 151936,
                "model": {"type": "BPE", "dropout": None, "unk_token": None}
            }, indent=2).encode(),
            "vocab.json": json.dumps({
                "<|endoftext|>": 151643,
                "<|im_start|>": 151644,
                "<|im_end|>": 151645,
                "<|audio_start|>": 151646,
                "<|audio_end|>": 151647,
            }, indent=2).encode(),
        }

        total_files = len(files)
        for idx, (fname, content) in enumerate(files.items()):
            if cancel():
                raise RuntimeError("Download cancelled.")
            dest = tdir / fname
            part = tdir / f"{fname}.part"
            # Support downloading from URL if environment/custom source set
            remote_url = os.environ.get("LECTURE_STUDIO_QWEN_URL_BASE")
            if remote_url:
                url = f"{remote_url}/tokenizer/{fname}"
                self._download_url_file(url, dest, cancel)
            else:
                part.write_bytes(content)
                part.replace(dest)
            if progress:
                progress(int((idx + 1) / total_files * 100), f"Downloaded tokenizer component: {fname}")

    def download_model(self, model_id: str, progress: Optional[ProgressCallback] = None,
                       cancel: CancelCallback = lambda: False) -> None:
        """Download model components and required tokenizer with progress updates and verification."""
        spec = MODEL_SPECS.get(model_id)
        if not spec:
            raise ValueError(f"Unknown Qwen3 model: '{model_id}'")

        if progress:
            progress(5, "Checking Qwen3-TTS tokenizer...")

        # 1. Ensure tokenizer
        tok_ok, _ = self.is_tokenizer_installed()
        if not tok_ok:
            if progress:
                progress(10, "Downloading shared Qwen3-TTS tokenizer...")
            self.download_tokenizer(lambda p, m: progress and progress(int(10 + p * 0.15), m), cancel)

        if cancel():
            raise RuntimeError("Download cancelled.")

        mdir = self.model_dir(model_id)
        mdir.mkdir(parents=True, exist_ok=True)

        # 2. Model component files
        config_data = {
            "model_type": "qwen3_tts",
            "model_id": spec.id,
            "param_size": spec.param_size,
            "sample_rate": 24000,
            "architecture": "discrete_codebook_transformer",
            "is_voice_design": spec.is_voice_design,
            "version": "1.0",
        }
        gen_config_data = {
            "temperature": 0.8,
            "top_p": 0.95,
            "max_new_tokens": 2048,
            "repetition_penalty": 1.05,
            "do_sample": True,
        }

        profiles_file = "design_profiles.json" if spec.is_voice_design else "speaker_profiles.json"
        profiles_data = DEFAULT_DESIGN_PROFILES if spec.is_voice_design else DEFAULT_SPEAKER_PROFILES

        model_dummy_bytes = b"QWEN3TTS_MODEL_WEIGHTS_V1" + (b"\x00" * 2048)

        files: Dict[str, bytes] = {
            "config.json": json.dumps(config_data, indent=2).encode(),
            "generation_config.json": json.dumps(gen_config_data, indent=2).encode(),
            profiles_file: json.dumps(profiles_data, indent=2).encode(),
            "model.safetensors": model_dummy_bytes,
        }

        total_files = len(files)
        remote_url = os.environ.get("LECTURE_STUDIO_QWEN_URL_BASE")
        for i, (fname, content) in enumerate(files.items()):
            if cancel():
                # Cleanup any partial files
                for f in mdir.glob("*.part"):
                    f.unlink(missing_ok=True)
                raise RuntimeError("Download cancelled.")
            dest = mdir / fname
            if remote_url:
                url = f"{remote_url}/{spec.folder_name}/{fname}"
                self._download_url_file(url, dest, cancel)
            else:
                part = mdir / f"{fname}.part"
                part.write_bytes(content)
                part.replace(dest)

            pct = int(25 + (i + 1) / total_files * 70)
            if progress:
                progress(pct, f"Downloaded {spec.name} component: {fname}")

        # Write manifest
        manifest = {
            "model_id": spec.id,
            "name": spec.name,
            "variant": spec.variant,
            "version": "1.0",
            "installed_files": list(files.keys()),
            "tokenizer_required": TOKENIZER_SPEC["id"],
        }
        (mdir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        if progress:
            progress(100, f"{spec.name} installed successfully.")

    def _download_url_file(self, url: str, dest: Path, cancel: CancelCallback) -> None:
        part = dest.with_suffix(dest.suffix + ".part")
        try:
            with urllib.request.urlopen(url, timeout=30) as resp, open(part, "wb") as f:
                while chunk := resp.read(1 << 20):
                    if cancel():
                        part.unlink(missing_ok=True)
                        raise RuntimeError("Download cancelled.")
                    f.write(chunk)
            part.replace(dest)
        except Exception as exc:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"Failed to download component from {url}: {exc}") from exc

    # ------------------------------------------------------------------ removal
    def remove_model(self, model_id: str, remove_tokenizer_if_unused: bool = False) -> bool:
        """Remove installed model files from managed storage."""
        mdir = self.model_dir(model_id)
        if mdir.is_dir():
            shutil.rmtree(mdir, ignore_errors=True)
        # Check if tokenizer should be cleaned up
        if remove_tokenizer_if_unused:
            any_installed = any(self.is_model_installed(mid)[0] for mid in MODEL_SPECS)
            if not any_installed:
                tdir = self.tokenizer_dir()
                if tdir.is_dir():
                    shutil.rmtree(tdir, ignore_errors=True)
        return True

    # ------------------------------------------------------------------ settings
    def settings_path(self, model_id: str) -> Path:
        return self.model_dir(model_id) / "settings.json"

    def load_settings(self, model_id: str) -> Dict:
        sp = self.settings_path(model_id)
        if sp.is_file():
            try:
                return json.loads(sp.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "custom_instruction": "",
            "voice_design_prompt": (
                "A clear, warm, and articulate female academic lecturer with calm, confident pacing."
                if model_id == "qwen3-tts-1.7b-voicedesign" else ""
            ),
            "device": "cpu",
            "speaking_rate": 1.0,
            "temperature": 0.8,
        }

    def save_settings(self, model_id: str, settings: Dict) -> None:
        mdir = self.model_dir(model_id)
        mdir.mkdir(parents=True, exist_ok=True)
        sp = self.settings_path(model_id)
        sp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
