"""Atomic file operations and disk utilities."""
import os
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict


def atomic_write_json(file_path: str | Path, data: Dict[str, Any], indent: int = 2) -> None:
    """Write JSON to a temporary file in the same directory and atomically rename it."""
    path = Path(file_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temp file in the same directory to ensure same filesystem for atomic rename
    with tempfile.NamedTemporaryFile("w", dir=str(path.parent), delete=False, encoding="utf-8") as tf:
        json.dump(data, tf, indent=indent, ensure_ascii=False)
        tf.flush()
        os.fsync(tf.fileno())
        temp_name = tf.name

    shutil.move(temp_name, str(path))


def read_json(file_path: str | Path) -> Dict[str, Any]:
    """Safely read and parse a JSON file."""
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Project file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def copy_source_file(src_path: str | Path, dest_dir: str | Path, new_name: str | None = None) -> Path:
    """Safely copy a source presentation file into the project's source directory."""
    src = Path(src_path).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"Source file does not exist: {src}")

    dest_folder = Path(dest_dir).resolve()
    dest_folder.mkdir(parents=True, exist_ok=True)

    filename = new_name if new_name else src.name
    dest = dest_folder / filename
    shutil.copy2(str(src), str(dest))
    return dest
