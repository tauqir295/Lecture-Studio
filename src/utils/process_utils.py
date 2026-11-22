"""Process execution and CLI tool checks (FFmpeg, LibreOffice, Piper) for Windows, macOS and Linux."""
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, Optional, Tuple

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"


def no_window_kwargs() -> Dict[str, Any]:
    """subprocess kwargs that stop a console window flashing up for each child process on Windows."""
    if IS_WINDOWS:
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def _program_files() -> list[str]:
    return [p for p in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                        os.environ.get("LOCALAPPDATA")) if p]


def find_tool(tool_name: str, extra_paths: Optional[list[str]] = None) -> Optional[str]:
    """Locate a command-line tool on PATH or in common Windows/macOS/Linux install locations."""
    path = shutil.which(tool_name)
    if path:
        return path

    candidates = extra_paths or []
    if tool_name in ("libreoffice", "soffice"):
        candidates.extend([
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            "/usr/bin/libreoffice",
            "/usr/local/bin/libreoffice",
            "/snap/bin/libreoffice",
        ])
        candidates.extend(os.path.join(p, "LibreOffice", "program", "soffice.exe") for p in _program_files())
    elif tool_name in ("ffmpeg", "ffprobe"):
        candidates.extend([
            "/usr/local/bin/" + tool_name,
            "/opt/homebrew/bin/" + tool_name,
            "/usr/bin/" + tool_name,
            "/snap/bin/" + tool_name,
        ])
        candidates.extend(os.path.join(p, "ffmpeg", "bin", tool_name + ".exe") for p in _program_files())
    elif tool_name == "piper":
        candidates.extend([
            "/usr/local/bin/piper",
            "/opt/homebrew/bin/piper",
            os.path.expanduser("~/.local/bin/piper"),
        ])

    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c

    return None


def run_process(cmd: list[str], timeout: int = 120) -> Tuple[int, str, str]:
    """Run an external command and return (exit_code, stdout, stderr)."""
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        **no_window_kwargs(),
    )
    return proc.returncode, proc.stdout, proc.stderr
