"""Application logging configuration."""
import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logger(
    name: str = "ppt_lecture_studio",
    log_dir: Optional[str | Path] = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """Configures and returns a hierarchical logger with console and optional file output."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers if already configured
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s.%(funcName)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_dir:
        log_path = Path(log_dir).resolve()
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path / "studio.log", encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
