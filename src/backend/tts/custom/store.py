"""Library of user-imported TTS models (name, format, files), stored as JSON in the models folder.

    <models_root>/tts/custom/models.json      registry   (folder overridable: LECTURE_STUDIO_CUSTOM_MODELS)
    <models_root>/tts/custom/<id>/            copies of model files ("copy into library" imports)

Models imported "in place" are referenced where they are; removing them never deletes those files.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from src.backend.tts.custom.formats import FORMATS, Detection
from src.utils.file_utils import atomic_write_json

ID_PREFIX = "custom-"


class ModelStoreError(RuntimeError):
    pass


class CustomModelStore:
    def __init__(self, root: Optional[Path] = None):
        if root is None:
            env = os.environ.get("LECTURE_STUDIO_CUSTOM_MODELS")
            if env:
                root = Path(env).expanduser()
            else:
                from src.backend.tts.registry import models_root
                root = models_root() / "tts" / "custom"
        self.root = Path(root)
        self.file = self.root / "models.json"

    # ------------------------------------------------------------------ persistence
    def entries(self) -> List[Dict]:
        try:
            data = json.loads(self.file.read_text(encoding="utf-8")) if self.file.is_file() else {}
        except (OSError, ValueError):
            return []
        return [e for e in data.get("models", []) if isinstance(e, dict) and e.get("id") and e.get("format")]

    def _save(self, entries: List[Dict]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.file, {"version": 1, "models": entries})

    def get(self, model_id: str) -> Optional[Dict]:
        return next((e for e in self.entries() if e["id"] == model_id), None)

    # ------------------------------------------------------------------ operations
    def _unique_id(self, name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "model"
        taken = {e["id"] for e in self.entries()}
        mid, i = ID_PREFIX + slug, 2
        while mid in taken:
            mid, i = f"{ID_PREFIX}{slug}-{i}", i + 1
        return mid

    def _check_name(self, name: str, exclude: str = "") -> str:
        name = (name or "").strip()
        if not name:
            raise ModelStoreError("Please enter a name for the model.")
        if any(e["name"].lower() == name.lower() and e["id"] != exclude for e in self.entries()):
            raise ModelStoreError(f"A model named '{name}' already exists.")
        return name

    def add(self, det: Detection, name: str, copy: bool = False, license_note: str = "",
            progress: Optional[Callable[[int, str], None]] = None) -> Dict:
        """Register a detected model. With `copy`, its files are copied into the library first."""
        if not det.ok:
            raise ModelStoreError(det.message or "This model cannot be imported.")
        if det.format not in FORMATS:
            raise ModelStoreError(f"Unknown model format '{det.format}'.")
        name = self._check_name(name)
        mid = self._unique_id(name)
        files = {role: str(Path(p).resolve()) for role, p in det.files.items()}
        if copy:
            dest = self.root / mid
            dest.mkdir(parents=True, exist_ok=True)
            try:
                total = len(files)
                for i, (role, src) in enumerate(list(files.items())):
                    if progress:
                        progress(int(100 * i / total), f"Copying {Path(src).name}…")
                    target = dest / Path(src).name
                    shutil.copy2(src, target)
                    files[role] = str(target.resolve())
            except OSError as exc:
                shutil.rmtree(dest, ignore_errors=True)
                raise ModelStoreError(f"Could not copy the model files: {exc}") from exc
        entry = {"id": mid, "name": name, "format": det.format, "files": files, "managed": bool(copy),
                 "license": license_note.strip(), "imported": datetime.now().isoformat(timespec="seconds")}
        self._save(self.entries() + [entry])
        if progress:
            progress(100, "Imported.")
        return entry

    def rename(self, model_id: str, name: str) -> None:
        entries = self.entries()
        e = next((x for x in entries if x["id"] == model_id), None)
        if not e:
            raise ModelStoreError("Model not found.")
        e["name"] = self._check_name(name, exclude=model_id)
        self._save(entries)

    def set_license(self, model_id: str, text: str) -> None:
        entries = self.entries()
        for e in entries:
            if e["id"] == model_id:
                e["license"] = text.strip()
        self._save(entries)

    def remove(self, model_id: str, delete_files: bool = False) -> None:
        """Unregister a model. `delete_files` deletes only the library copy (never in-place originals)."""
        entries = self.entries()
        e = next((x for x in entries if x["id"] == model_id), None)
        if not e:
            return
        self._save([x for x in entries if x["id"] != model_id])
        if delete_files and e.get("managed"):
            d = (self.root / model_id).resolve()
            if d.parent == self.root.resolve() and d.name.startswith(ID_PREFIX) and d.is_dir():
                shutil.rmtree(d, ignore_errors=True)

    def missing_files(self, entry: Dict) -> List[str]:
        return [p for p in entry.get("files", {}).values() if not os.path.isfile(p)]
