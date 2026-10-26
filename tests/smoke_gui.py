"""Offscreen smoke test. Never registers global keys or sends game input."""
import sys
from pathlib import Path
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow
from ui.calibration import CalibrationDialog, capture_steps
from core.config import Config, write_json
from core.image_detector import required_templates
import json
import cv2
import numpy as np

app = QApplication([])
with tempfile.TemporaryDirectory() as directory:
    with patch("ui.main_window.app_root", return_value=Path(directory)), patch("ui.main_window.HotkeyManager"):
        window = MainWindow()
        assert window.quantity.minimum() == 1
        assert window.quantity.maximum() == 20
        assert window.quantity.value() == 15
        assert not window.live.isChecked()
        assert window.single_cycle.isChecked()
        window.quantity.setValue(20)
        assert (Path(directory) / "config.json").is_file()
        config = Config(quantity=15)
        dialog = CalibrationDialog(config, Path(directory), window)
        names = [step[0] for step in capture_steps(15)]
        assert len(names) == len(set(names))
        assert set(required_templates(15)).issubset(names)
        assert dialog.name.itemData(0) == "shop_menu"
        assert dialog.name.findData("shop_target_identity") == -1
        assert dialog.name.findData("shop_target") >= 0
        dialog.move_item(1)
        assert dialog.name.currentData() == "shop_open"
        # Test a partially calibrated profile using a synthetic game frame.
        target = np.random.default_rng(7).integers(30, 240, (12, 12, 3), dtype=np.uint8)
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        frame[20:32, 30:42] = target
        dialog.path.parent.mkdir(parents=True)
        cv2.imencode(".png", target)[1].tofile(str(dialog.path.parent / "shop_menu.png"))
        write_json(dialog.path, {"resolution": [2560, 1440], "templates": {
            "shop_menu": {"file": "shop_menu.png", "roi": [0, 0, 100, 100], "threshold": .97}}, "regions": {}})
        dialog.test_names = ["shop_menu"]
        dialog.data = json.loads(dialog.path.read_text(encoding="utf-8"))
        dialog.name.setCurrentIndex(dialog.name.findData("shop_menu"))
        dialog.update_saved_preview()
        assert not dialog.saved_preview.pixmap().isNull()
        assert "shop_menu.png" in dialog.preview_details.text()
        assert not dialog.action_enabled.isChecked()
        assert dialog.action_choice.itemData(0) == "npc"
        with patch("ui.calibration.GameWindow"), patch("ui.calibration.ScreenCapture") as capture:
            capture.return_value.capture.return_value = frame
            dialog.run_recognition_test()
            capture.return_value.capture.assert_called_once_with(foreground=True)
        assert "[찾음]" in dialog.test_results.toPlainText()
        assert dialog.view.overlays
        dialog.reject()
        window.close()
        for handler in window.logger.handlers[:]:
            handler.close()
            window.logger.removeHandler(handler)
print("GUI smoke test passed (no game input)")
