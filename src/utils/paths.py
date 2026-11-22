"""Path resolution and directory structure management."""
from pathlib import Path
from typing import Dict


class ProjectPaths:
    """Manages paths for a self-contained project directory."""

    def __init__(self, project_dir: str | Path):
        self.root = Path(project_dir).resolve()
        self.source = self.root / "source"
        self.slides = self.root / "slides"
        self.preview = self.root / "preview"
        self.narration = self.root / "narration"
        self.audio = self.root / "audio"
        self.subtitles = self.root / "subtitles"
        self.video = self.root / "video"
        self.cache = self.root / "cache"
        self.logs = self.root / "logs"
        self.project_json = self.root / "project.json"

    def ensure_directories(self) -> None:
        """Create all required subdirectories if they do not exist."""
        for d in [
            self.root,
            self.source,
            self.slides,
            self.preview,
            self.narration,
            self.audio,
            self.subtitles,
            self.video,
            self.cache,
            self.logs,
        ]:
            d.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> Dict[str, str]:
        return {
            "root": str(self.root),
            "source": str(self.source),
            "slides": str(self.slides),
            "preview": str(self.preview),
            "narration": str(self.narration),
            "audio": str(self.audio),
            "subtitles": str(self.subtitles),
            "video": str(self.video),
            "cache": str(self.cache),
            "logs": str(self.logs),
            "project_json": str(self.project_json),
        }
