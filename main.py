"""Application entry point for PPT Lecture Studio."""
import sys
from pathlib import Path
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src.frontend.main_window import MainWindow
from src.utils.logging_config import setup_logger

logger = setup_logger("app_main")


APP_ID = "lecture-studio"


def app_icon(root: Path) -> QIcon:
    """Multi-size window/taskbar icon built from the generated icon set (falls back to the master)."""
    icon = QIcon()
    icons = root / "assets" / "icons"
    for png in sorted((icons / "hicolor").glob(f"*/apps/{APP_ID}.png")):
        icon.addFile(str(png))
    if icon.isNull():
        icon.addFile(str(root / "assets" / "icon.png"))
    return icon


def main() -> None:
    if sys.platform.startswith("win"):
        # Own taskbar group + icon instead of python.exe's.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"LectureStudio.{APP_ID}")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("PPT Lecture Studio")
    app.setOrganizationName("PPTLectureStudio")

    workspace = Path(__file__).resolve().parent
    app.setDesktopFileName(APP_ID)             # matches the Linux .desktop entry (Wayland icon lookup)
    app.setWindowIcon(app_icon(workspace))

    window = MainWindow(workspace_root=workspace)
    window.show()

    logger.info("Application started.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
