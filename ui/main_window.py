import logging
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QSpinBox, QPushButton, QPlainTextEdit, QCheckBox, QMessageBox)

from core.config import Config, app_root
from core.controller import run
from core.hotkey_manager import HotkeyManager
from core.state_machine import RunControl, State, Stopped
from ui.calibration import CalibrationDialog


class Worker(QThread):
    message = Signal(str)
    state = Signal(str)

    def __init__(self, config, root, control):
        super().__init__()
        self.config, self.root, self.control = config, root, control

    def run(self):
        try:
            run(self.config, self.root, self.control, self.message.emit, lambda s: self.state.emit(s.value))
        except Stopped:
            self.message.emit("사용자 중지. 자동 재개하지 않습니다.")
            self.state.emit(State.STOPPED.value)
        except Exception as error:
            logging.getLogger("macro").exception("실행 실패")
            self.message.emit(f"{type(error).__name__}: {error}")
            self.state.emit(State.ERROR.value)
        else:
            self.state.emit(State.IDLE.value)


class MainWindow(QMainWindow):
    start_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self.root = app_root()
        self.worker = None
        self.control = None
        self.current_state = State.IDLE.value
        self.closing = False
        self.calibration_dialog = None
        (self.root / "logs").mkdir(exist_ok=True)
        self.logger = logging.getLogger("macro")
        self.logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(self.root / "logs/macro.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.logger.addHandler(handler)
        try:
            self.config = Config.load(self.root)
            config_error = None
        except Exception as error:
            self.config = Config()
            config_error = str(error)
        # Never restore live mode automatically across app launches.
        self.config.live_input = False
        self.setWindowTitle("Conqueror's Blade Macro")
        self.resize(780, 540)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.addWidget(QLabel("버들잎 면갑 구매 → 최대 15개씩 분해 | 2560×1440 전체 창 모드"))
        row = QHBoxLayout()
        row.addWidget(QLabel("구매 수량"))
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 20)
        self.quantity.setValue(self.config.quantity)
        self.quantity.valueChanged.connect(self.save_quantity)
        row.addWidget(self.quantity)
        self.calibrate = QPushButton("화면 캡처 / 보정")
        self.calibrate.clicked.connect(self.open_calibration)
        row.addWidget(self.calibrate)
        layout.addLayout(row)
        self.live = QCheckBox("실제 게임 입력 활성화 (보정 검토 필요 · 재실행 시 해제)")
        layout.addWidget(self.live)
        buttons = QHBoxLayout()
        self.start_button = QPushButton("F6 시작 / 읽기 전용 진단")
        self.pause_button = QPushButton("F7 일시정지")
        self.resume_button = QPushButton("F8 재개")
        self.stop_button = QPushButton("F9 즉시 중지")
        for button, action in [(self.start_button, self.start), (self.pause_button, self.pause),
                               (self.resume_button, self.resume), (self.stop_button, self.stop)]:
            button.clicked.connect(action)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.status = QLabel(State.IDLE.value)
        layout.addWidget(self.status)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        layout.addWidget(self.log_view, 1)
        self.start_requested.connect(self.start)
        self.pause_requested.connect(self.pause)
        self.resume_requested.connect(self.resume)
        self.stop_requested.connect(self.stop)
        try:
            self.hotkeys = HotkeyManager({"f6": self.start_requested.emit, "f7": self.request_pause,
                                          "f8": self.resume_requested.emit, "f9": self.request_stop})
        except Exception as error:
            self.hotkeys = None
            self.log("단축키 등록 실패: " + str(error) + " / 실제 입력 사용 불가")
            self.live.setEnabled(False)
        if config_error:
            self.log("설정 파일 오류, 기본값 사용: " + config_error)
        self.log("실제 입력 비활성화. 보정 이미지 없이는 실행되지 않습니다.")

    def log(self, message):
        self.logger.info(message)
        self.log_view.appendPlainText(message)

    def save_quantity(self, value):
        self.config.quantity = value
        self.config.live_input = False
        try:
            self.config.save(self.root)
        except OSError as error:
            self.log("설정 저장 실패: " + str(error))

    def open_calibration(self):
        if self.worker and self.worker.isRunning():
            return
        self.live.setChecked(False)
        self.calibration_dialog = CalibrationDialog(self.config, self.root, self)
        try:
            self.calibration_dialog.exec()
        finally:
            self.calibration_dialog = None

    def set_state(self, text):
        self.current_state = text
        self.status.setText(State.PAUSED.value if self.control and not self.control.running.is_set() else text)

    def start(self):
        if self.calibration_dialog is not None:
            return
        if self.worker and self.worker.isRunning():
            return
        if self.live.isChecked() and not self.hotkeys:
            self.log("중지 단축키가 없어 실제 입력을 거부합니다.")
            return
        config = Config(**vars(self.config))
        config.live_input = self.live.isChecked()
        self.control = RunControl()
        self.worker = Worker(config, self.root, self.control)
        self.worker.message.connect(self.log)
        self.worker.state.connect(self.set_state)
        self.worker.finished.connect(self.finished)
        self.quantity.setEnabled(False)
        self.calibrate.setEnabled(False)
        self.live.setEnabled(False)
        self.start_button.setEnabled(False)
        self.worker.start()

    def request_pause(self):
        if self.control:
            self.control.pause()
        self.pause_requested.emit()

    def request_stop(self):
        # Set the thread-safe event directly from the hotkey callback, before Qt dispatch.
        if self.control:
            self.control.stop()
        if self.calibration_dialog is not None:
            self.calibration_dialog.stop_action()
        self.stop_requested.emit()

    def pause(self):
        if self.control and self.worker and self.worker.isRunning():
            self.control.pause()
            self.status.setText(State.PAUSED.value)

    def resume(self):
        if self.control and self.worker and self.worker.isRunning():
            self.control.resume()
            self.status.setText(self.current_state)

    def stop(self):
        if self.control:
            self.control.stop()

    def finished(self):
        self.quantity.setEnabled(True)
        self.calibrate.setEnabled(True)
        self.live.setEnabled(self.hotkeys is not None)
        self.live.setChecked(False)
        self.start_button.setEnabled(True)
        if self.closing:
            self.close()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.closing = True
            self.stop()
            self.log("작업 중지 후 창을 닫습니다.")
            event.ignore()
            return
        if self.hotkeys:
            self.hotkeys.close()
        super().closeEvent(event)
