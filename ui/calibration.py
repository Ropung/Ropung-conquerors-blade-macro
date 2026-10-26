import json
import logging
from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QRect, Signal, QTimer, QThread
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QComboBox, QMessageBox, QScrollArea, QPlainTextEdit, QCheckBox)

from core.config import write_json
from core.image_detector import Detector, Profile, required_templates, valid_rect
from core.screen_capture import GameWindow, ScreenCapture
from core.state_machine import batches, RunControl, Stopped
from core.step_test import NAVIGATION_STEPS, run_step_test


LABELS = {
    "shop_menu": "NPC 메뉴의 마구 상점 항목",
    "shop_open": "마구 상점이 열린 화면의 고정 표시",
    "page_two": "상점 2페이지 이동 버튼",
    "page_two_active": "상점 2페이지 선택 표시",
    "shop_target": "상점의 버들잎 면갑 항목 (이름·파란 등급 포함)",
    "buy_button": "상점 구매 버튼",
    "buy_popup": "구매 수량 창의 고정 제목/표시",
    "quantity_field": "구매 수량 입력칸",
    "quantity_plus": "구매 수량 + 버튼",
    "quantity_minus": "구매 수량 − 버튼",
    "buy_confirm": "구매 수량 창의 최종 구매 확인 버튼",
    "buy_target_name": "구매 확인 창의 버들잎 면갑 이름",
    "buy_target_blue": "구매 확인 창의 파란 등급 표시",
    "inventory_open": "인벤토리가 열린 화면의 고정 표시",
    "dismantle_icon": "인벤토리 왼쪽 네 번째 분해 아이콘",
    "dismantle_panel": "분해 창의 고정 제목/표시",
    "inventory_target": "인벤토리의 버들잎 면갑 아이콘",
    "inventory_target_name": "인벤토리 툴팁의 버들잎 면갑 이름",
    "inventory_target_blue": "인벤토리 툴팁의 파란 등급 표시",
    "slot_target": "버들잎 면갑이 등록된 분해 칸 이미지",
    "slot_empty": "비어 있는 분해 칸 이미지",
    "dismantle_button": "분해 실행 버튼",
    "complete_popup": "분해 완료, 확인하세요 안내 문구",
    "complete_confirm": "분해 완료 창의 확인 버튼",
    "inventory": "전체 인벤토리 아이템 검색 영역",
}


def korean_label(name):
    if name.startswith("quantity_") and name[9:].isdigit():
        return f"구매 수량 {name[9:]}개 표시 (입력칸 전체)"
    if name.startswith("buy_cost_"):
        return f"구매 비용 {int(name[9:]):,} 전쟁 코인 표시"
    if name.startswith("dismantle_cost_"):
        return f"분해 비용 {int(name[15:]):,} 전쟁 코인 표시"
    if name.startswith("slot_") and name[5:].isdigit():
        return f"분해 {int(name[5:]) + 1}번 칸 영역 (총 15칸)"
    return LABELS.get(name, name)


def is_region(name):
    return name == "inventory" or (name.startswith("slot_") and name[5:].isdigit())


def capture_steps(quantity):
    groups = [
        ("NPC 메뉴", "게임에서 F키를 누른 뒤 NPC 메뉴를 캡처하세요.", ["shop_menu"]),
        ("상점", "마구 상점을 클릭해 들어간 화면을 캡처하세요.", ["shop_open", "page_two"]),
        ("상점 2페이지", "2페이지로 이동한 화면을 캡처하세요.", ["page_two_active", "shop_target", "buy_button"]),
        ("구매 수량 창", f"구매 버튼을 누르고 수량을 {quantity}개로 입력한 화면을 캡처하세요. 최종 구매는 아직 누르지 마세요.",
         list(dict.fromkeys(["buy_popup", "quantity_field", f"quantity_{quantity}", "buy_target_name", "buy_target_blue", f"buy_cost_{quantity * 1600}", "buy_confirm"]))),
        ("구매 수량 1개", "수량을 1개로 맞춰 비용 1,600 표시만 캡처하세요.", ["buy_cost_1600"] if quantity != 1 else []),
        ("인벤토리", "상점을 닫고 I키로 인벤토리를 연 화면을 캡처하세요.", ["inventory_open", "dismantle_icon"]),
        ("빈 분해 창", "왼쪽 네 번째 분해 아이콘을 누르고, 분해 칸이 모두 빈 화면을 캡처하세요.",
         ["dismantle_panel", "inventory", "slot_empty", *[f"slot_{i}" for i in range(15)]]),
        ("인벤토리 대상", "인벤토리에 버들잎 면갑이 있는 화면을 캡처하세요.", ["inventory_target"]),
        ("인벤토리 아이템 설명", "인벤토리의 버들잎 면갑에 마우스를 올려 설명이 보이게 한 뒤 캡처하세요.", ["inventory_target_name", "inventory_target_blue"]),
        ("분해 등록", "대상만 분해 칸에 등록한 화면을 캡처하세요. 분해 실행 버튼은 아직 누르지 마세요.", ["slot_target", "dismantle_button"]),
    ]
    for amount in dict.fromkeys([*batches(quantity), 1]):
        groups.append((f"{amount}개 분해 비용", f"버들잎 면갑 {amount}개만 등록하고 비용이 {amount * 300:,}인지 확인한 화면을 캡처하세요.", [f"dismantle_cost_{amount * 300}"]))
    groups.append(("분해 완료", "수동 분해 테스트 후 완료 팝업이 보일 때 캡처하세요. 확인을 누르기 전에 두 항목을 저장하세요.", ["complete_popup", "complete_confirm"]))
    return [(name, stage, hint) for stage, hint, names in groups for name in names]


class CropView(QLabel):
    selected = Signal(object)

    def __init__(self, frame):
        super().__init__()
        self.frame = frame
        self.start = None
        self.rect = QRect()
        self.overlays = []
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = QImage(rgb.data, 2560, 1440, rgb.strides[0], QImage.Format.Format_RGB888).copy()
        self.setPixmap(QPixmap.fromImage(image))
        self.setFixedSize(2560, 1440)

    def mousePressEvent(self, event):
        self.start = event.position().toPoint()
        self.rect = QRect(self.start, self.start)

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.rect = QRect(self.start, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        if self.start is not None:
            self.rect = QRect(self.start, event.position().toPoint()).normalized().intersected(self.rect_for_frame())
            self.start = None
            self.selected.emit(self.rect)
            self.update()

    def rect_for_frame(self):
        return QRect(0, 0, 2560, 1440)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(Qt.GlobalColor.red, 2))
        painter.drawRect(self.rect)
        for rect, label, color in self.overlays:
            painter.setPen(QPen(color, 3))
            painter.drawRect(rect)
            painter.drawText(rect.x(), max(15, rect.y() - 4), label)


class NavigationWorker(QThread):
    message = Signal(str)
    captured = Signal(object)

    def __init__(self, config, root, control, key, parent=None):
        super().__init__(parent)
        self.config, self.root, self.control, self.key = config, root, control, key

    def run(self):
        try:
            frame = run_step_test(self.config, self.root, self.control, self.key, self.message.emit)
            self.captured.emit(frame)
            self.message.emit("선택 동작 1회 완료. 다음 동작은 자동 실행하지 않습니다.")
        except Stopped:
            self.message.emit("F9/사용자 요청으로 동작 테스트 중지")
        except Exception as error:
            self.message.emit(f"동작 테스트 중지: {error}")


class CalibrationDialog(QDialog):
    def __init__(self, config, root, parent=None):
        super().__init__(parent)
        self.config, self.root = config, root
        self.path = root / config.profile
        self.data = (json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists()
                     else {"resolution": [2560, 1440], "templates": {}, "regions": {}, "reviewed_quantities": []})
        self.view = None
        self.test_timer = QTimer(self)
        self.test_timer.setSingleShot(True)
        self.test_timer.timeout.connect(self.run_recognition_test)
        self.test_names = []
        self.restore_parent = False
        self.action_worker = None
        self.action_control = None
        self.close_after_action = False
        self.setWindowTitle("2560×1440 게임 화면 보정 (읽기 전용 캡처)")
        self.resize(1200, 850)
        layout = QVBoxLayout(self)
        info = QLabel("게임 UI를 수동으로 열고 [캡처] → 영역 드래그 → [저장]. 모든 좌표는 원본 픽셀입니다.\n"
                      "버튼은 글자와 테두리를 포함해 드래그하세요. 이름·등급은 상점/구매창/인벤토리별로 저장합니다. 수량·비용은 입력칸 전체를 선택하세요.")
        info.setWordWrap(True)
        layout.addWidget(info)
        row = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItems(["순서대로 전체 (처음부터 보정)", "찾을 이미지만", "검색 영역만"])
        self.name = QComboBox()
        row.addWidget(self.kind)
        row.addWidget(self.name, 1)
        capture = QPushButton("게임 캡처")
        capture.clicked.connect(self.capture)
        row.addWidget(capture)
        save = QPushButton("선택 영역 저장")
        save.clicked.connect(self.save_crop)
        row.addWidget(save)
        layout.addLayout(row)
        navigation = QHBoxLayout()
        previous = QPushButton("이전 항목")
        previous.clicked.connect(lambda: self.move_item(-1))
        following = QPushButton("다음 항목")
        following.clicked.connect(lambda: self.move_item(1))
        navigation.addWidget(previous)
        navigation.addWidget(following)
        layout.addLayout(navigation)
        tests = QHBoxLayout()
        selected_test = QPushButton("선택 항목 인식 테스트 (3초 후)")
        selected_test.clicked.connect(lambda: self.schedule_test(False))
        stage_test = QPushButton("현재 단계 전체 인식 테스트 (3초 후)")
        stage_test.clicked.connect(lambda: self.schedule_test(True))
        tests.addWidget(selected_test)
        tests.addWidget(stage_test)
        layout.addLayout(tests)
        self.stage_text = QLabel()
        self.stage_text.setWordWrap(True)
        layout.addWidget(self.stage_text)
        self.help_text = QLabel()
        self.help_text.setWordWrap(True)
        layout.addWidget(self.help_text)
        preview_row = QHBoxLayout()
        self.saved_preview = QLabel("저장된 기준 이미지: 항목을 선택하세요.")
        self.saved_preview.setMinimumHeight(64)
        preview_row.addWidget(self.saved_preview, 1)
        self.preview_details = QLabel()
        self.preview_details.setWordWrap(True)
        preview_row.addWidget(self.preview_details, 1)
        enlarge = QPushButton("저장 이미지 원본 보기")
        enlarge.clicked.connect(self.show_saved_image)
        preview_row.addWidget(enlarge)
        layout.addLayout(preview_row)
        self.action_enabled = QCheckBox("동작 테스트에서 실제 키·클릭 허용 (구매 확정·분해 실행 제외)")
        layout.addWidget(self.action_enabled)
        actions = QHBoxLayout()
        self.action_choice = QComboBox()
        for key, label, _ in NAVIGATION_STEPS:
            self.action_choice.addItem(label, key)
        actions.addWidget(self.action_choice, 1)
        action_button = QPushButton("선택 동작 1회 실행 (3초 후 · F9 중지)")
        action_button.clicked.connect(self.start_action)
        actions.addWidget(action_button)
        layout.addLayout(actions)
        self.name.currentIndexChanged.connect(self.show_help)
        self.status = QLabel("캡처 대기")
        layout.addWidget(self.status)
        self.scroll = QScrollArea()
        layout.addWidget(self.scroll, 1)
        self.test_results = QPlainTextEdit()
        self.test_results.setReadOnly(True)
        self.test_results.setMaximumHeight(140)
        self.test_results.setPlaceholderText("인식 테스트는 실제 게임 화면을 새로 캡처합니다. 클릭·키 입력·구매·분해는 하지 않습니다.")
        layout.addWidget(self.test_results)
        review = QPushButton("현재 수량의 템플릿/비용/영역을 수동 검토 완료로 표시")
        review.clicked.connect(self.review)
        layout.addWidget(review)
        self.kind.currentIndexChanged.connect(self.fill_names)
        self.fill_names()

    def fill_names(self):
        self.name.clear()
        for number, (name, stage, _) in enumerate(capture_steps(self.config.quantity), 1):
            if self.kind.currentIndex() == 1 and is_region(name):
                continue
            if self.kind.currentIndex() == 2 and not is_region(name):
                continue
            self.name.addItem(f"{number:02d}. [{stage}] {korean_label(name)}", name)
        # Continue from the first unsaved item without changing existing crops.
        for index in range(self.name.count()):
            name = self.name.itemData(index)
            if name not in self.data["regions" if is_region(name) else "templates"]:
                self.name.setCurrentIndex(index)
                break
        self.show_help()

    def move_item(self, offset):
        self.name.setCurrentIndex(max(0, min(self.name.count() - 1, self.name.currentIndex() + offset)))

    def show_help(self):
        name = self.name.currentData()
        if not name:
            self.help_text.clear()
            self.stage_text.clear()
            self.saved_preview.clear()
            self.preview_details.clear()
            return
        _, stage, instructions = next(step for step in capture_steps(self.config.quantity) if step[0] == name)
        self.stage_text.setText(f"현재 단계: {stage}\n{instructions}")
        if self.view is not None:
            self.view.rect = QRect()
            self.view.update()
        if name == "shop_target":
            hint = "버들잎 면갑의 아이콘·이름·파란 등급이 함께 보이는 상점 항목을 선택하세요. 별도 툴팁 캡처는 필요 없습니다."
        elif is_region(name):
            hint = "아이템을 검사할 영역 전체를 드래그하세요. 분해 칸은 한 칸씩 따로 지정합니다."
        elif name in ("buy_button", "buy_confirm", "dismantle_button", "complete_confirm", "page_two", "shop_menu", "dismantle_icon"):
            hint = "이 버튼의 글자·아이콘과 테두리가 들어가도록 드래그하세요. 일치한 이미지의 가운데를 클릭합니다."
        elif "cost_" in name or name.startswith("quantity_"):
            hint = "숫자 일부만 자르지 말고 통화 표시 또는 입력칸 테두리까지 포함해 전체 값을 선택하세요."
        else:
            hint = "해당 글자·아이콘이 선명하게 들어가도록 드래그하세요. 화면이 바뀌면 게임 캡처를 다시 누르세요."
        saved = name in self.data["regions" if is_region(name) else "templates"]
        self.help_text.setText(f"{'저장됨' if saved else '미저장'} · {hint}")
        self.update_saved_preview()

    def saved_image_path(self):
        name = self.name.currentData()
        spec = self.data.get("templates", {}).get(name)
        if not spec or is_region(name):
            return None
        path = (self.path.parent / spec["file"]).resolve()
        return path if path.is_relative_to(self.path.parent.resolve()) else None

    def update_saved_preview(self):
        name = self.name.currentData()
        path = self.saved_image_path()
        pixmap = QPixmap(str(path)) if path and path.is_file() else QPixmap()
        self.saved_preview.clear()
        if not pixmap.isNull():
            self.saved_preview.setPixmap(pixmap.scaled(360, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.preview_details.setText(f"저장된 기준 이미지\n{path.name}\n원본 {pixmap.width()}×{pixmap.height()} 픽셀")
        elif name and is_region(name):
            self.saved_preview.setText("검색 영역은 이미지 파일이 아닙니다.")
            self.preview_details.setText(str(self.data.get("regions", {}).get(name, "미저장")))
        else:
            self.saved_preview.setText("저장된 이미지 없음")
            self.preview_details.setText("해당 항목을 캡처해 저장하세요.")

    def show_saved_image(self):
        path = self.saved_image_path()
        pixmap = QPixmap(str(path)) if path and path.is_file() else QPixmap()
        if pixmap.isNull():
            QMessageBox.information(self, "저장 이미지", "저장된 이미지가 없습니다. 검색 영역 항목은 PNG를 저장하지 않습니다.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("저장된 기준 이미지 원본 · " + path.name)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(str(path)))
        scroll = QScrollArea()
        image = QLabel()
        image.setPixmap(pixmap)
        scroll.setWidget(image)
        layout.addWidget(scroll)
        dialog.resize(min(1000, max(450, pixmap.width()+60)), min(700, max(250, pixmap.height()+100)))
        dialog.exec()

    def start_action(self):
        if self.test_timer.isActive() or (self.action_worker and self.action_worker.isRunning()):
            return
        if not self.action_enabled.isChecked():
            QMessageBox.information(self, "동작 테스트", "실제 키·클릭 허용을 먼저 체크하세요. 인식만 확인하려면 위의 인식 테스트를 사용하세요.")
            return
        if not self.parentWidget() or not getattr(self.parentWidget(), "hotkeys", None):
            QMessageBox.warning(self, "동작 테스트", "F9 중지 단축키가 등록되어 있어야 합니다.")
            return
        key = self.action_choice.currentData()
        definition = next(item for item in NAVIGATION_STEPS if item[0] == key)
        required = list(definition[2])
        if key == "quantity":
            required.append(f"quantity_{self.config.quantity}")
        try:
            profile = Profile(self.path)
            missing = [name for name in required if name not in profile.templates]
            if missing:
                description = "\n".join("• " + korean_label(name) for name in missing)
                message = "아직 실행하지 않았습니다. 아래 이미지를 먼저 저장하세요:\n\n" + description
                self.record_action_message(message)
                self.status.setText("동작 실행 전 중지 · 필요한 이미지 미저장")
                if self.kind.currentIndex() != 0:
                    self.kind.setCurrentIndex(0)
                index = self.name.findData(missing[0])
                if index >= 0:
                    self.name.setCurrentIndex(index)
                QMessageBox.information(self, "먼저 저장할 이미지", message)
                return
            # Validate only the files this action needs, before minimizing windows.
            Detector(profile, names=required)
        except Exception as error:
            self.record_action_message("동작 실행 전 중지: " + str(error))
            QMessageBox.warning(self, "동작 준비 실패", str(error))
            return
        self.action_control = RunControl()
        self.action_worker = NavigationWorker(self.config, self.root, self.action_control, key, self)
        self.test_results.clear()
        self.action_worker.message.connect(self.record_action_message)
        self.action_worker.captured.connect(self.show_action_capture)
        self.action_worker.finished.connect(self.finish_action)
        self.restore_parent = self.parentWidget().isVisible()
        self.showMinimized()
        self.parentWidget().showMinimized()
        self.action_worker.start()

    def record_action_message(self, message):
        logging.getLogger("macro").info("동작 테스트: %s", message)
        self.test_results.appendPlainText(message)

    def stop_action(self):
        # May be called by the keyboard hook thread. Only touches a thread-safe event.
        if self.action_control:
            self.action_control.stop()

    def show_action_capture(self, frame):
        self.view = CropView(frame)
        self.view.selected.connect(lambda r: self.status.setText(f"선택: x={r.x()}, y={r.y()}, w={r.width()}, h={r.height()}"))
        self.scroll.setWidget(self.view)

    def finish_action(self):
        self.action_enabled.setChecked(False)
        self.restore_test_windows()
        self.status.setText("동작 테스트 종료. 결과를 확인한 뒤 다음 동작을 직접 선택하세요.")
        if self.close_after_action:
            self.reject()

    def capture(self):
        capture = None
        try:
            capture = ScreenCapture(GameWindow(self.config.window_title))
            frame = capture.capture(foreground=False)
            self.view = CropView(frame)
            self.view.selected.connect(lambda r: self.status.setText(f"선택: x={r.x()}, y={r.y()}, w={r.width()}, h={r.height()}"))
            self.scroll.setWidget(self.view)
            self.status.setText("캡처 완료. 원본 화면을 스크롤하여 영역을 선택하세요.")
        except Exception as error:
            QMessageBox.warning(self, "캡처 실패", str(error))
        finally:
            if capture:
                capture.close()

    def schedule_test(self, whole_stage):
        name = self.name.currentData()
        if not name or self.test_timer.isActive() or (self.action_worker and self.action_worker.isRunning()):
            return
        steps = capture_steps(self.config.quantity)
        stage = next(stage for key, stage, _ in steps if key == name)
        self.test_names = [key for key, group, _ in steps if group == stage] if whole_stage else [name]
        self.status.setText("3초 뒤 현재 게임 화면을 검사합니다. 게임을 보이게 하고 필요한 툴팁을 띄우세요.")
        self.restore_parent = bool(self.parentWidget() and self.parentWidget().isVisible())
        self.showMinimized()
        if self.restore_parent:
            self.parentWidget().showMinimized()
        self.test_timer.start(3000)

    def restore_test_windows(self):
        if self.restore_parent and self.parentWidget():
            self.parentWidget().showNormal()
        self.restore_parent = False
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def run_recognition_test(self):
        capture = None
        reports, overlays = [], []
        try:
            profile = Profile(self.path)
            # No full-profile validation: unfinished stages may be tested separately.
            names = [name for name in self.test_names if not is_region(name) and name in profile.templates]
            capture = ScreenCapture(GameWindow(self.config.window_title))
            frame = capture.capture(foreground=True)
            detector = Detector(profile, names=names)
            for name in self.test_names:
                label = korean_label(name)
                if is_region(name):
                    region = profile.regions.get(name)
                    if valid_rect(region):
                        overlays.append((QRect(*region), label, Qt.GlobalColor.yellow))
                        reports.append(f"[영역 표시] {label}: {region} (아이템 인식 결과 아님)")
                    else:
                        reports.append(f"[미저장/오류] {label}")
                    continue
                if name not in profile.templates:
                    reports.append(f"[미저장] {label}: 먼저 이미지를 저장하세요.")
                    continue
                regions = [(None, None)]
                if name == "inventory_target" and "inventory" in profile.regions:
                    regions = [(None, profile.regions["inventory"])]
                elif name in ("slot_empty", "slot_target"):
                    regions = [(f"{i+1}번 칸", profile.regions[f"slot_{i}"]) for i in range(15) if f"slot_{i}" in profile.regions] or regions
                for region_label, region in regions:
                    title = label + (f" / {region_label}" if region_label else "")
                    try:
                        result = detector.diagnose(frame, name, region)
                        count = len(result["matches"])
                        multiple_ok = name in ("inventory_target", "slot_target", "slot_empty")
                        outcome = "찾음" if count == 1 or (multiple_ok and count > 0) else "못 찾음" if count == 0 else "여러 곳 일치 · 자동 실행 불가"
                        reports.append(f"[{outcome}] {title}: {count}개 / 최고 유사도 {result['similarity']:.1%} / 기준 {result['threshold']:.1%}")
                        tw, th = result["size"]
                        color = Qt.GlobalColor.green if count == 1 or multiple_ok else Qt.GlobalColor.magenta
                        for x, y in result["matches"]:
                            overlays.append((QRect(x-tw//2, y-th//2, tw, th), title, color))
                        if count == 0:
                            overlays.append((QRect(*result["best"]), title + " (기준 미달)", Qt.GlobalColor.darkYellow))
                    except Exception as error:
                        reports.append(f"[검사 오류] {title}: {error}")
            self.view = CropView(frame)
            self.view.overlays = overlays
            self.view.selected.connect(lambda r: self.status.setText(f"선택: x={r.x()}, y={r.y()}, w={r.width()}, h={r.height()}"))
            self.scroll.setWidget(self.view)
            if overlays:
                first = overlays[0][0]
                self.scroll.ensureVisible(first.center().x(), first.center().y(), 150, 100)
            self.status.setText("인식 테스트 완료 · 실제 입력 0회 · 초록: 찾음 / 노랑: 영역 또는 기준 미달 / 자홍: 모호함")
        except Exception as error:
            reports.append(f"[테스트 실패] {error}")
            self.status.setText("인식 테스트 실패. 아래 결과를 확인하세요.")
        finally:
            if capture:
                capture.close()
            self.test_results.setPlainText("\n".join(reports))
            self.restore_test_windows()

    def reject(self):
        if self.action_worker and self.action_worker.isRunning():
            self.close_after_action = True
            self.stop_action()
            return
        self.test_timer.stop()
        if self.restore_parent and self.parentWidget():
            self.parentWidget().showNormal()
        self.restore_parent = False
        super().reject()

    def save_crop(self):
        if self.view is None or min(self.view.rect.width(), self.view.rect.height()) < 5:
            QMessageBox.warning(self, "영역 필요", "먼저 5×5 이상 영역을 선택하세요.")
            return
        rect = self.view.rect
        roi = [rect.x(), rect.y(), rect.width(), rect.height()]
        name = self.name.currentData()
        if not is_region(name):
            x, y, w, h = roi
            crop = self.view.frame[y:y+h, x:x+w]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            ok, encoded = cv2.imencode(".png", crop)
            if not ok:
                raise RuntimeError("PNG 저장 실패")
            encoded.tofile(str(self.path.parent / (name + ".png")))
            # Search near the calibrated position; inventory icons use inventory ROI at runtime.
            margin = 12
            left, top = max(0, x-margin), max(0, y-margin)
            search = [left, top, min(2560, x+w+margin)-left, min(1440, y+h+margin)-top]
            if name.startswith("inventory_target_"):
                # Tooltip position follows whichever inventory cell is hovered.
                search = [0, 0, 2560, 1440]
            self.data["templates"][name] = {"file": name + ".png", "roi": search, "threshold": .90}
        else:
            self.data["regions"][name] = roi
        self.data["reviewed_quantities"] = []
        write_json(self.path, self.data)
        self.status.setText(korean_label(name) + " 저장 완료. 변경으로 기존 검토 표시는 해제되었습니다.")
        if self.name.currentIndex() < self.name.count() - 1:
            self.move_item(1)
        else:
            self.show_help()
            self.status.setText(korean_label(name) + " 저장 완료. 마지막 항목입니다. 미저장 항목과 보정 내용을 검토하세요.")

    def review(self):
        try:
            profile = Profile(self.path)
            profile.validate(self.config.quantity)
            Detector(profile)
        except Exception as error:
            QMessageBox.warning(self, "미완료", str(error))
            return
        message = (f"{self.config.quantity}개 수량 표시, 구매 비용 {self.config.quantity * 1600:,}, 파란 버들잎 면갑 이름·등급, "
                   "분해 비용(개당 300), 전체 인벤토리, 서로 겹치지 않는 15개 슬롯을 실제 화면에서 확인했습니까?\n"
                   "이 표시는 실게임 테스트 통과를 의미하지 않습니다. 최초 실행은 1개 수량으로 진행하세요.")
        if QMessageBox.question(self, "수동 보정 검토", message) == QMessageBox.StandardButton.Yes:
            reviewed = self.data.setdefault("reviewed_quantities", [])
            if self.config.quantity not in reviewed:
                reviewed.append(self.config.quantity)
            write_json(self.path, self.data)
            self.status.setText("현재 수량 보정 검토 표시 완료")
