"""Project manager handling persistence, lifecycle, and directory creation."""
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from src.models.project import Project, WorkflowStage
from src.models.video_config import VideoConfig
from src.utils.paths import ProjectPaths
from src.utils.file_utils import atomic_write_json, read_json, copy_source_file
from src.utils.logging_config import setup_logger

logger = setup_logger("project_manager")


class ProjectDeleteError(RuntimeError):
    """Raised when a project folder may not or could not be deleted."""


def slugify(name: str) -> str:
    """Generate a filesystem-friendly directory name."""
    s = re.sub(r"[^\w\s-]", "", name).strip().lower()
    return re.sub(r"[-\s]+", "_", s) or "project"


class ProjectManager:
    """Manages project creation, disk persistence, and loading."""

    def __init__(self, workspace_root: Optional[str | Path] = None):
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd()
        self.projects_dir = self.workspace_root / "Projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def create_project(
        self,
        name: str,
        source_path: str | Path,
        custom_dir: Optional[str | Path] = None,
        settings: Optional[VideoConfig] = None,
    ) -> Project:
        """Create a new project directory structure and copy the presentation source."""
        source_file = Path(source_path).resolve()
        if not source_file.is_file():
            raise FileNotFoundError(f"Source presentation file not found: {source_file}")

        proj_id = slugify(name)
        target_dir = Path(custom_dir).resolve() if custom_dir else (self.projects_dir / proj_id)

        # Handle name collisions
        counter = 1
        base_target = target_dir
        while target_dir.exists() and (target_dir / "project.json").exists():
            target_dir = Path(f"{base_target}_{counter}")
            proj_id = target_dir.name
            counter += 1

        paths = ProjectPaths(target_dir)
        paths.ensure_directories()

        # Copy source presentation into project source/
        ext = source_file.suffix.lower()
        from src.backend.content.importers import detect_type
        source_type = detect_type(source_file)
        copied_source = copy_source_file(source_file, paths.source, f"original{ext}")

        # Set up logger in project directory
        setup_logger(f"project_{proj_id}", log_dir=paths.logs)

        project = Project(
            project_id=proj_id,
            project_name=name,
            version=1,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            source_file=f"source/{copied_source.name}",
            source_type=source_type,
            workflow_stage=WorkflowStage.IMPORTED,
            slides_approved=False,
            narration_approved=False,
            audio_generated=False,
            video_exported=False,
            settings=settings or VideoConfig(),
            project_dir=str(target_dir),
        )

        self.save_project(project)
        logger.info(f"Created project '{name}' at {target_dir}")
        return project

    def save_project(self, project: Project) -> None:
        """Atomically persist project state to project.json."""
        if not project.project_dir:
            raise ValueError("Project has no project_dir set.")

        project_dir = Path(project.project_dir).resolve()
        paths = ProjectPaths(project_dir)
        paths.ensure_directories()

        project.updated_at = datetime.now().isoformat()
        atomic_write_json(paths.project_json, project.to_dict())
        logger.debug(f"Saved project state to {paths.project_json}")

    def load_project(self, project_dir: str | Path) -> Project:
        """Load and deserialize a project from its project.json."""
        p_dir = Path(project_dir).resolve()
        json_path = p_dir / "project.json"
        if not json_path.is_file():
            raise FileNotFoundError(f"No project.json found at {p_dir}")

        data = read_json(json_path)
        project = Project.from_dict(data, project_dir=str(p_dir))
        logger.info(f"Loaded project '{project.project_name}' from {p_dir}")
        return project

    # ------------------------------------------------------------------ recent projects
    @property
    def _recent_file(self) -> Path:
        return self.projects_dir / ".recent.json"

    def _read_recent(self) -> Dict[str, List[str]]:
        try:
            data = read_json(self._recent_file) if self._recent_file.is_file() else {}
        except Exception as e:
            logger.warning(f"Ignoring unreadable recent-projects file: {e}")
            data = {}
        return {"hidden": list(data.get("hidden", [])), "external": list(data.get("external", []))}

    def _write_recent(self, data: Dict[str, List[str]]) -> None:
        atomic_write_json(self._recent_file, data)

    @staticmethod
    def _key(path: str | Path) -> str:
        return os.path.normcase(str(Path(path).resolve()))

    def add_recent(self, project_dir: str | Path) -> None:
        """Show a project in Recent Projects (un-hides it; remembers projects outside Projects/)."""
        key, data = self._key(project_dir), self._read_recent()
        data["hidden"] = [h for h in data["hidden"] if self._key(h) != key]
        inside = Path(project_dir).resolve().parent == self.projects_dir.resolve()
        if not inside and key not in {self._key(e) for e in data["external"]}:
            data["external"].append(str(Path(project_dir).resolve()))
        self._write_recent(data)

    def remove_from_recent(self, project_dir: str | Path) -> None:
        """Hide a project from Recent Projects. No files are touched."""
        key, data = self._key(project_dir), self._read_recent()
        data["external"] = [e for e in data["external"] if self._key(e) != key]
        if Path(project_dir).resolve().parent == self.projects_dir.resolve() and \
                key not in {self._key(h) for h in data["hidden"]}:
            data["hidden"].append(str(Path(project_dir).resolve()))
        self._write_recent(data)

    @staticmethod
    def _summary(item: Path) -> Optional[Dict[str, Any]]:
        json_path = item / "project.json"
        if not json_path.is_file():
            return None
        try:
            data = read_json(json_path)
        except Exception as e:
            logger.warning(f"Failed to read project at {item}: {e}")
            return None
        mtime = datetime.fromtimestamp(json_path.stat().st_mtime).isoformat(timespec="seconds")
        return {
            "project_id": data.get("project_id", item.name),
            "project_name": data.get("project_name", item.name),
            "workflow_stage": data.get("workflow_stage", "imported"),
            "slide_count": data.get("slide_count", 0),
            "updated_at": data.get("updated_at") or mtime,
            "project_dir": str(item),
        }

    def list_projects(self) -> List[Dict[str, Any]]:
        """Recent projects, newest first: projects in Projects/ plus ones opened from elsewhere,
        minus those removed from the list."""
        recent = self._read_recent()
        hidden = {self._key(h) for h in recent["hidden"]}
        dirs = [d for d in self.projects_dir.iterdir() if d.is_dir()] if self.projects_dir.is_dir() else []
        dirs += [Path(e) for e in recent["external"] if Path(e).is_dir()]
        projects, seen = [], set()
        for item in dirs:
            key = self._key(item)
            if key in hidden or key in seen:
                continue
            seen.add(key)
            info = self._summary(item)
            if info:
                projects.append(info)
        projects.sort(key=lambda p: p["updated_at"], reverse=True)
        return projects

    def delete_project(self, project_dir: str | Path) -> None:
        """Permanently delete one project folder and everything in it.

        Refuses anything that is not a real project folder: missing project.json, a symlink, the
        workspace, Projects/ itself, the home folder or a filesystem root. Symlinks inside the
        project are removed, never followed, so nothing outside the folder is deleted.
        """
        raw = Path(project_dir)
        if raw.is_symlink():
            raise ProjectDeleteError("The project folder is a link; it was not deleted.")
        target = raw.resolve()
        protected = {self._key(p) for p in (self.workspace_root, self.projects_dir, Path.home(),
                                             Path(target.anchor))}
        if self._key(target) in protected or len(target.parts) < 3:
            raise ProjectDeleteError(f"Refusing to delete a protected folder: {target}")
        if not target.is_dir() or not (target / "project.json").is_file():
            raise ProjectDeleteError(f"Not a Lecture Studio project folder (no project.json): {target}")

        errors: List[str] = []

        def on_error(func, path, exc):
            # Retry once after clearing read-only flags (common on Windows), then record.
            try:
                os.chmod(path, 0o700)
                func(path)
            except Exception as e2:
                errors.append(f"{path}: {e2}")

        kw = {"onexc": on_error} if sys.version_info >= (3, 12) else {"onerror": on_error}
        shutil.rmtree(target, **kw)
        if errors or target.exists():
            raise ProjectDeleteError("Some files could not be deleted:\n" + "\n".join(errors[:10]))
        key, data = self._key(target), self._read_recent()     # forget it entirely
        data = {k: [x for x in v if self._key(x) != key] for k, v in data.items()}
        self._write_recent(data)
        logger.info(f"Deleted project folder {target}")
