"""Pytest configuration and session fixtures for Qt tests."""
import os
import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """Ensure a single shared QApplication instance throughout the test run."""
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    return app
