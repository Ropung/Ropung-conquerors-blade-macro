"""Offscreen smoke test. Never registers global keys or sends game input."""
import sys
from pathlib import Path
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

app = QApplication([])
with tempfile.TemporaryDirectory() as directory:
    with patch("ui.main_window.app_root", return_value=Path(directory)), patch("ui.main_window.HotkeyManager"):
        window = MainWindow()
        assert window.quantity.minimum() == 1
        assert window.quantity.maximum() == 20
        assert window.quantity.value() == 15
        assert not window.live.isChecked()
        window.quantity.setValue(20)
        assert (Path(directory) / "config.json").is_file()
        window.close()
        for handler in window.logger.handlers[:]:
            handler.close()
            window.logger.removeHandler(handler)
print("GUI smoke test passed (no game input)")
