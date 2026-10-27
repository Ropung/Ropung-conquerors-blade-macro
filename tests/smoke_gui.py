"""Offscreen smoke test. Never registers global keys or sends game input."""
import sys
from pathlib import Path
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRect
from ui.main_window import MainWindow
from ui.calibration import CalibrationDialog, CropView, capture_steps
from core.config import Config, write_json
from core.image_detector import required_templates, Profile, Detector
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
        window.resolution_box.setCurrentIndex(3)
        assert window.config.resolution == (1920, 1080)
        assert Config.load(Path(directory)).resolution == (1920, 1080)
        small_view = CropView(np.zeros((1080, 1920, 3), dtype=np.uint8))
        assert small_view.width() == 1920 and small_view.height() == 1080
        assert small_view.rect_for_frame().width() == 1920
        fhd_dialog = CalibrationDialog(window.config, Path(directory), window)
        assert fhd_dialog.data['resolution'] == [1920, 1080]
        assert fhd_dialog.path == Path(directory) / 'calibration/1920x1080/profile.json'
        window.show()
        fhd_dialog.show()
        with patch('ui.calibration.GameWindow') as game_window, patch('ui.calibration.ScreenCapture') as capture:
            capture.return_value.capture.return_value = np.zeros((1080, 1920, 3), dtype=np.uint8)
            fhd_dialog.capture()
            assert not window.isVisible() and not fhd_dialog.isVisible()
            assert fhd_dialog.capture_timer.isActive()
            fhd_dialog.capture_timer.stop()
            fhd_dialog.capture_now()
            game_window.assert_called_once_with(window.config.window_title, (1920, 1080))
            assert window.isVisible() and fhd_dialog.isVisible()
            assert fhd_dialog.view.width() == 1920
        fhd_dialog.reject()
        assert window.single_cycle.isChecked()
        assert window.max_dismantle.value() == 15
        assert "실행 결과" in window.result_summary.text()
        assert window.stop_reason.text() == ""
        window.show_failure("inventory_target_name: 인식 실패")
        assert "인벤토리 대상 이름" in window.stop_reason.text()
        window.started_at = window.last_update_at = 0
        window.refresh_progress()
        assert "경과" in window.status.text()
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
        wizard = CalibrationDialog(Config(), Path(directory) / 'wizard', window)
        assert wizard.tabs.count() == 4
        wizard.name.setCurrentIndex(wizard.name.findData('buy_button'))
        wizard.stage_frames[wizard.current_stage()] = frame
        wizard.install_capture(frame, wizard.current_stage())
        wizard.show_help()
        wizard.view.rect = QRect(30, 20, 12, 12)
        wizard.save_crop()
        assert wizard.pending_crop == QRect(30, 20, 12, 12)
        assert wizard.view.click_point is not None
        assert not wizard.path.exists()  # Nothing saved until search area is confirmed.
        wizard.view.rect = QRect(0, 0, 10, 10)
        with patch('ui.calibration.QMessageBox.warning') as warning:
            wizard.save_crop()
            warning.assert_called_once()
        assert not wizard.path.exists()
        wizard.view.rect = QRect(0, 0, 100, 100)
        wizard.save_crop()
        stored = json.loads(wizard.path.read_text(encoding='utf-8'))
        assert stored['templates']['buy_button']['roi'] == [0, 0, 100, 100]
        assert stored['templates']['buy_button']['crop'] == [30, 20, 12, 12]
        assert wizard.view is None  # Next stage requires its own game screen.
        wizard.name.setCurrentIndex(wizard.name.findData('buy_button'))
        assert wizard.view is not None  # Previous capture is reused.
        wizard.data['reviewed_quantities'] = [15]
        wizard.threshold.setValue(70)
        wizard.save_threshold()
        stored = json.loads(wizard.path.read_text(encoding='utf-8'))
        assert stored['templates']['buy_button']['threshold'] == .70
        assert stored['reviewed_quantities'] == []
        detector = Detector(Profile(wizard.path), names=['buy_button'])
        assert detector.diagnose(frame, 'buy_button')['threshold'] == .70
        wizard.name.setCurrentIndex(wizard.name.findData('shop_target'))
        assert wizard.view.frame is frame  # Same screen, no recapture.
        assert wizard.threshold.value() == 90  # Per-item, not global.
        wizard.reject()
        window.close()
        for handler in window.logger.handlers[:]:
            handler.close()
            window.logger.removeHandler(handler)
print("GUI smoke test passed (no game input)")
