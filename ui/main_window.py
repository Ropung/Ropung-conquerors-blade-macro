import logging
import time
import json
from datetime import datetime
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QThread, Signal, QTimer, Qt
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QSpinBox, QPushButton, QPlainTextEdit, QCheckBox, QMessageBox, QProgressBar, QApplication, QComboBox)

from core.config import Config, app_root
from core.controller import run, run_dismantle_once
from core.hotkey_manager import HotkeyManager
from core.state_machine import RunControl, State, Stopped
from ui.calibration import CalibrationDialog


class Worker(QThread):
    message = Signal(str)
    state = Signal(str)
    failed = Signal(str)

    def __init__(self, config, root, control, single_cycle=True, dismantle_only=False, max_dismantle=0):
        super().__init__()
        self.config, self.root, self.control = config, root, control
        self.single_cycle = single_cycle
        self.dismantle_only = dismantle_only
        self.max_dismantle = max_dismantle
        self.result_text = ""

    def run(self):
        started = time.monotonic()
        outcome = "완료"
        try:
            if self.dismantle_only:
                run_dismantle_once(self.config, self.root, self.control, self.message.emit, lambda s: self.state.emit(s.value))
            else:
                run(self.config, self.root, self.control, self.message.emit, lambda s: self.state.emit(s.value), single_cycle=self.single_cycle, max_dismantle=self.max_dismantle)
        except Stopped:
            outcome = "사용자 중지"
            self.message.emit("사용자 중지. 자동 재개하지 않습니다.")
            self.state.emit(State.STOPPED.value)
        except Exception as error:
            outcome = "오류 중지: " + str(error)
            logging.getLogger("macro").exception("실행 실패")
            self.message.emit(f"{type(error).__name__}: {error}")
            self.failed.emit(str(error))
            self.state.emit(State.ERROR.value)
        else:
            self.state.emit(State.IDLE.value)
        finally:
            elapsed = round(time.monotonic() - started, 1)
            self.result_text = f"실행 결과 · {outcome} · {elapsed}초\n" + self.control.stats.text()
            self.message.emit(self.result_text)
            try:
                folder = self.root / "logs" / "results"
                folder.mkdir(parents=True, exist_ok=True)
                report = {**self.control.stats.report(), "outcome": outcome, "elapsed_seconds": elapsed,
                          "max_dismantle": self.max_dismantle, "live_input": self.config.live_input}
                (folder / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as error:
                self.message.emit("결과 파일 저장 실패: " + str(error))


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
        self.started_at = None
        self.last_update_at = None
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(500)
        self.progress_timer.timeout.connect(self.refresh_progress)
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
        layout.addWidget(QLabel("버들잎 면갑 구매 → 최대 15개씩 분해 | 게임 해상도를 아래에서 선택하세요"))
        resolution_row = QHBoxLayout()
        resolution_row.addWidget(QLabel("게임 해상도"))
        self.resolution_box = QComboBox()
        sizes = [(1280, 720), (1366, 768), (1600, 900), (1920, 1080), (1920, 1200),
                 (2560, 1080), (2560, 1440), (2560, 1600), (3440, 1440), (3840, 2160)]
        if self.config.resolution not in sizes:
            sizes.append(self.config.resolution)
        for size in sizes:
            self.resolution_box.addItem(f"{size[0]} × {size[1]}", size)
        self.resolution_box.setCurrentIndex(sizes.index(self.config.resolution))
        self.resolution_box.currentIndexChanged.connect(self.save_resolution)
        resolution_row.addWidget(self.resolution_box)
        layout.addLayout(resolution_row)
        layout.addWidget(QLabel("해상도별로 보정 이미지를 따로 저장합니다. 변경 후 해당 해상도에서 보정하세요."))
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
        limit_row = QHBoxLayout()
        limit_row.addWidget(QLabel("최대 분해 개수"))
        self.max_dismantle = QSpinBox()
        self.max_dismantle.setRange(0, 1_000_000)
        self.max_dismantle.setSpecialValueText("제한 없음")
        self.max_dismantle.setValue(15)
        limit_row.addWidget(self.max_dismantle)
        limit_row.addWidget(QLabel("도달하면 자동 중지 · 0은 제한 없음"))
        layout.addLayout(limit_row)
        self.live = QCheckBox("실제 게임 입력 활성화 (보정 검토 필요 · 재실행 시 해제)")
        layout.addWidget(self.live)
        self.single_cycle = QCheckBox("1회 테스트 후 자동 중지 (처음에는 1개로 테스트)")
        self.single_cycle.setChecked(True)
        layout.addWidget(self.single_cycle)
        buttons = QHBoxLayout()
        self.start_button = QPushButton("F6 시작 / 읽기 전용 진단")
        self.pause_button = QPushButton("F7 일시정지")
        self.resume_button = QPushButton("F10 재개")
        self.stop_button = QPushButton("F9 즉시 중지")
        for button, action in [(self.start_button, self.start), (self.pause_button, self.pause),
                               (self.resume_button, self.resume), (self.stop_button, self.stop)]:
            button.clicked.connect(action)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.dismantle_test_button = QPushButton("기존 아이템 분해만 1회 테스트 (구매 안 함)")
        self.dismantle_test_button.clicked.connect(self.start_dismantle_test)
        layout.addWidget(self.dismantle_test_button)
        tooltips = {
            self.resolution_box: "게임 내부 화면 크기와 같게 선택하세요. 해상도별로 보정 파일을 따로 사용하며 게임 자체의 해상도를 바꾸지는 않습니다.",
            self.quantity: "한 번에 구매할 수량(1~20)입니다. 20개는 최대 15개씩 나누어 분해합니다. 해당 수량의 비용·이미지 보정이 필요합니다.",
            self.calibrate: "① 캡처·보정 → ② 인식 확인 → ③ 동작 테스트 → ④ 최종 검토 순서로 준비합니다. 버튼과 항목 위에 마우스를 올리면 설명을 볼 수 있습니다.",
            self.max_dismantle: "이번 실행에서 분해할 최대 개수입니다. 0은 제한 없음입니다. 1회 테스트가 켜져 있으면 그보다 먼저 한 사이클 후 중지할 수 있습니다.",
            self.live: "꺼져 있으면 F6은 읽기 전용 진단입니다. 켜면 실제 구매·분해로 코인과 아이템이 소모됩니다. 보정 검토와 단축키 등록이 필요합니다.",
            self.single_cycle: "구매→분해 한 사이클을 마치면 자동 중지합니다. 반복 실행하려면 해제하세요. 실행 종료 후 다시 켜집니다.",
            self.start_button: "실제 입력이 꺼져 있으면 화면 진단만 합니다. 켜져 있으면 준비 상태를 검사한 뒤 자동 구매·분해를 시작합니다.",
            self.pause_button: "진행 중인 작업을 일시정지합니다. 재개는 F10입니다. 이미 실행된 클릭이나 구매를 되돌리지는 않습니다.",
            self.resume_button: "일시정지한 작업을 재개합니다. 멈추기 전 좌표가 더 이상 유효하지 않으면 안전 중지할 수 있습니다.",
            self.stop_button: "실행 중인 작업을 중지합니다. 이미 구매·분해한 결과는 되돌릴 수 없습니다. 게임 화면을 확인한 뒤 다시 시작하세요.",
            self.dismantle_test_button: "게임에서 분해 창을 열고 수량을 보유한 대상 개수(1~15)에 맞추세요. 추가 구매 없이 기존 아이템을 실제로 분해합니다.",
        }
        for widget, text in tooltips.items():
            widget.setToolTip(text)
            widget.setToolTipDuration(20000)
        self.status = QLabel(State.IDLE.value)
        layout.addWidget(self.status)
        self.activity = QProgressBar()
        self.activity.setRange(0, 1)
        self.activity.setValue(0)
        layout.addWidget(self.activity)
        self.current_step = QLabel("현재 단계: 대기")
        self.current_step.setWordWrap(True)
        layout.addWidget(self.current_step)
        self.stop_reason = QLabel()
        self.stop_reason.setWordWrap(True)
        self.stop_reason.setStyleSheet("color: #c62828; font-weight: bold;")
        layout.addWidget(self.stop_reason)
        self.result_summary = QLabel("실행 결과: 아직 실행하지 않았습니다.")
        self.result_summary.setWordWrap(True)
        self.result_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.result_summary)
        self.runtime_hint = QLabel("", self, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.runtime_hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.runtime_hint.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.runtime_hint.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.runtime_hint.setStyleSheet("background: #202020; color: white; padding: 8px; border: 1px solid #888;")
        self.runtime_hint.setWordWrap(True)
        screen = QApplication.primaryScreen().availableGeometry()
        self.runtime_hint.setGeometry(screen.x()+16, screen.bottom()-90, 660, 70)
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
                                          "f10": self.resume_requested.emit, "f9": self.request_stop})
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
        if self.worker and self.worker.isRunning():
            self.last_update_at = time.monotonic()
            self.current_step.setText("현재 단계: " + message)

    def show_failure(self, reason):
        labels = {"inventory_target_identity": "인벤토리 아이콘·이름·파란 등급 확인", "complete_popup": "분해 완료 팝업"}
        for key, label in labels.items():
            reason = reason.replace(key, label)
        self.stop_reason.setText("중지 이유: " + reason)

    def refresh_progress(self):
        if self.started_at is None:
            return
        elapsed = int(time.monotonic() - self.started_at)
        idle = int(time.monotonic() - (self.last_update_at or self.started_at))
        phase = State.PAUSED.value if self.control and not self.control.running.is_set() else self.current_state
        self.status.setText(f"실행 중 · {phase} · 경과 {elapsed}초 · 마지막 진행 {idle}초 전")
        self.runtime_hint.setText(self.status.text() + "\n" + self.current_step.text())

    def save_resolution(self, index):
        self.config.width, self.config.height = self.resolution_box.itemData(index)
        self.config.live_input = False
        self.live.setChecked(False)
        try:
            self.config.save(self.root)
            self.log(f"해상도 {self.config.width}×{self.config.height} 선택 / 보정 파일: {self.config.calibration_profile}")
        except OSError as error:
            self.log("설정 저장 실패: " + str(error))

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

    def start_dismantle_test(self):
        if self.calibration_dialog is not None or (self.worker and self.worker.isRunning()):
            return
        if not self.live.isChecked() or not self.hotkeys:
            QMessageBox.information(self, "분해 테스트", "실제 게임 입력 활성화를 체크하고 F9 중지 단축키 등록을 확인하세요.")
            return
        quantity = self.quantity.value()
        if not 1 <= quantity <= 15:
            QMessageBox.information(self, "분해 테스트", "이 테스트는 한 번에 1~15개입니다.")
            return
        text = f"기존 버들잎 면갑 {quantity}개를 실제로 분해합니다. 예상 비용 {quantity * 300:,} 전쟁 코인.\n구매는 하지 않으며 완료 후 중지합니다. 게임에서 분해 창을 열어두세요."
        if QMessageBox.question(self, "실제 분해 1회 테스트", text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.start(dismantle_only=True)

    def start(self, dismantle_only=False):
        if self.calibration_dialog is not None:
            return
        if self.worker and self.worker.isRunning():
            return
        if self.live.isChecked() and not self.hotkeys:
            self.log("중지 단축키가 없어 실제 입력을 거부합니다.")
            return
        config = Config(**vars(self.config))
        config.live_input = self.live.isChecked()
        limit = self.max_dismantle.value()
        if dismantle_only and limit and config.quantity > limit:
            QMessageBox.information(self, "분해 개수 제한", "기존 아이템 테스트 수량이 최대 분해 개수보다 큽니다. 수량 또는 제한을 조정하세요.")
            return
        self.control = RunControl()
        self.worker = Worker(config, self.root, self.control, self.single_cycle.isChecked(), dismantle_only=dismantle_only, max_dismantle=limit)
        self.worker.message.connect(self.log)
        self.worker.state.connect(self.set_state)
        self.worker.failed.connect(self.show_failure)
        self.worker.finished.connect(self.finished)
        self.quantity.setEnabled(False)
        self.resolution_box.setEnabled(False)
        self.max_dismantle.setEnabled(False)
        self.result_summary.setText("실행 결과: 작업 중")
        self.calibrate.setEnabled(False)
        self.live.setEnabled(False)
        self.single_cycle.setEnabled(False)
        self.start_button.setEnabled(False)
        self.dismantle_test_button.setEnabled(False)
        self.stop_reason.clear()
        self.current_step.setText("현재 단계: 시작 준비")
        self.current_state = State.CHECKING.value
        self.started_at = self.last_update_at = time.monotonic()
        self.activity.setRange(0, 0)
        self.progress_timer.start()
        if config.live_input:
            self.runtime_hint.setText("시작 준비 · F9 중지")
            self.runtime_hint.show()
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
        self.progress_timer.stop()
        self.activity.setRange(0, 1)
        self.activity.setValue(1 if self.current_state == State.IDLE.value else 0)
        elapsed = int(time.monotonic() - self.started_at) if self.started_at else 0
        outcome = "완료" if self.current_state == State.IDLE.value else self.current_state
        self.status.setText(f"{outcome} · 총 {elapsed}초 · 실행 종료")
        if self.runtime_hint.isVisible():
            self.runtime_hint.setText(self.status.text() + "\n" + (self.stop_reason.text() or self.current_step.text()))
        self.quantity.setEnabled(True)
        self.resolution_box.setEnabled(True)
        self.max_dismantle.setEnabled(True)
        if self.worker:
            self.result_summary.setText(self.worker.result_text)
        self.calibrate.setEnabled(True)
        self.live.setEnabled(self.hotkeys is not None)
        self.live.setChecked(False)
        self.single_cycle.setEnabled(True)
        self.single_cycle.setChecked(True)
        self.start_button.setEnabled(True)
        self.dismantle_test_button.setEnabled(True)
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
        self.runtime_hint.close()
        super().closeEvent(event)
