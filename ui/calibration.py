import json
import logging
from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QRect, Signal, QTimer, QThread
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QComboBox, QMessageBox, QScrollArea, QPlainTextEdit, QCheckBox,
                               QWidget, QTabWidget, QDoubleSpinBox)

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


CLICK_TARGETS = {"shop_menu", "page_two", "shop_target", "buy_button", "buy_confirm",
                 "dismantle_icon", "inventory_target", "dismantle_button", "complete_confirm"}


def target_role(name):
    if is_region(name):
        return "검색 영역 · 클릭 안 함"
    if name == "quantity_field":
        return "입력 대상 · 수량 입력칸"
    if name in CLICK_TARGETS:
        return "클릭 대상"
    return "확인 이미지 · 클릭 안 함"


def item_tooltip(name):
    role = target_role(name)
    if is_region(name):
        detail = "이미지를 자르는 작업이 아닙니다. 아이템을 찾을 범위만 지정합니다. 이 영역 자체는 클릭하지 않습니다."
    elif name == "buy_button":
        detail = "버들잎 면갑과 같은 줄의 구매 버튼 하나를 글자·테두리까지 선택하세요. 마우스는 버튼에서 떼고 촬영하세요. 다른 구매 버튼은 검색 범위에서 제외하세요."
    elif name == "quantity_field":
        detail = "수량 입력칸 전체를 테두리까지 선택합니다. 실제 입력 시 칸의 오른쪽 부분을 클릭합니다."
    elif name in CLICK_TARGETS:
        detail = "버튼·아이템 하나를 선택합니다. 인식한 이미지의 중앙이 클릭 대상입니다. 검색 범위는 다음 단계에서 별도로 지정합니다."
    elif "cost_" in name or name.startswith("quantity_"):
        detail = "전체 숫자와 통화 표시 또는 입력칸 테두리를 포함하세요. 숫자 일부만 자르면 다른 수량·비용을 잘못 인식할 수 있습니다. 클릭하지 않습니다."
    else:
        detail = "화면 상태를 확인하는 기준 이미지입니다. 해당 글자·아이콘을 선택하고 움직이는 배경은 제외하세요. 이 이미지는 클릭하지 않습니다."
    return f"{korean_label(name)}\n[{role}]\n{detail}"


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
        self.selection_color = Qt.GlobalColor.green
        self.click_point = None
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = QImage(rgb.data, frame.shape[1], frame.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
        self.setPixmap(QPixmap.fromImage(image))
        self.setFixedSize(frame.shape[1], frame.shape[0])

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
        return QRect(0, 0, self.frame.shape[1], self.frame.shape[0])

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(self.selection_color, 2))
        painter.drawRect(self.rect)
        for rect, label, color in self.overlays:
            painter.setPen(QPen(color, 3))
            painter.drawRect(rect)
            painter.drawText(rect.x(), max(15, rect.y() - 4), label)
        if self.click_point is not None:
            painter.setPen(QPen(Qt.GlobalColor.green, 3))
            painter.drawEllipse(self.click_point, 6, 6)
            painter.drawText(self.click_point, "  클릭 위치")


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
        self.path = root / config.calibration_profile
        self.data = (json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists()
                     else {"resolution": list(config.resolution), "templates": {}, "regions": {}, "reviewed_quantities": []})
        self.view = None
        self.pending_crop = None
        self.capture_stage = None
        self.stage_frames = {}
        self.test_timer = QTimer(self)
        self.test_timer.setSingleShot(True)
        self.test_timer.timeout.connect(self.run_recognition_test)
        self.capture_timer = QTimer(self)
        self.capture_timer.setSingleShot(True)
        self.capture_timer.timeout.connect(self.capture_now)
        self.test_names = []
        self.restore_parent = False
        self.action_worker = None
        self.action_control = None
        self.close_after_action = False
        self.setWindowTitle(f"{config.width}×{config.height} 게임 화면 보정 (읽기 전용 캡처)")
        self.resize(1200, 850)
        layout = QVBoxLayout(self)
        info = QLabel("① 같은 게임 화면은 한 번만 캡처 → 대상 자르기 → 검색 범위 확인·저장\n"
                      "② 인식 위치와 유사도 확인 → ③ 필요한 동작만 테스트 → ④ 최종 검토")
        info.setWordWrap(True)
        layout.addWidget(info)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        panels = []
        for title in ("① 캡처·보정", "② 인식 확인", "③ 동작 테스트", "④ 최종 검토"):
            page = QWidget()
            panels.append(QVBoxLayout(page))
            self.tabs.addTab(page, title)
        setup, recognition, actions_panel, review_panel = panels
        row = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItems(["순서대로 전체 (처음부터 보정)", "찾을 이미지만", "검색 영역만"])
        self.name = QComboBox()
        row.addWidget(self.kind)
        row.addWidget(self.name, 1)
        help_button = QPushButton("? 항목 설명")
        help_button.clicked.connect(lambda: QMessageBox.information(self, "현재 보정 항목", self.name.toolTip()))
        row.addWidget(help_button)
        capture = QPushButton("게임 캡처 (창 숨김 · 3초 후)")
        capture.clicked.connect(self.capture)
        setup.addWidget(capture)
        self.save_button = QPushButton("① 대상 선택 완료 → 검색 범위")
        self.save_button.clicked.connect(self.save_crop)
        setup.addWidget(self.save_button)
        restart = QPushButton("대상부터 다시 선택")
        restart.clicked.connect(self.show_help)
        setup.addWidget(restart)
        layout.insertLayout(1, row)
        navigation = QHBoxLayout()
        previous = QPushButton("이전 항목")
        previous.clicked.connect(lambda: self.move_item(-1))
        following = QPushButton("다음 항목")
        following.clicked.connect(lambda: self.move_item(1))
        navigation.addWidget(previous)
        navigation.addWidget(following)
        layout.insertLayout(2, navigation)
        tests = QHBoxLayout()
        selected_test = QPushButton("선택 항목 인식 테스트 (3초 후)")
        selected_test.clicked.connect(lambda: self.schedule_test(False))
        stage_test = QPushButton("현재 단계 전체 인식 테스트 (3초 후)")
        stage_test.clicked.connect(lambda: self.schedule_test(True))
        tests.addWidget(selected_test)
        tests.addWidget(stage_test)
        recognition.addWidget(QLabel("저장한 이미지가 실제 화면에서 어디에 잡히는지 확인합니다. 게임 입력은 하지 않습니다."))
        recognition.addLayout(tests)
        self.stage_text = QLabel()
        self.stage_text.setWordWrap(True)
        setup.addWidget(self.stage_text)
        self.help_text = QLabel()
        self.help_text.setWordWrap(True)
        setup.addWidget(self.help_text)
        threshold_row = QHBoxLayout()
        threshold_row.addWidget(QLabel("현재 이미지의 최소 유사도"))
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(50, 100)
        self.threshold.setDecimals(1)
        self.threshold.setSingleStep(1)
        self.threshold.setSuffix(" %")
        self.threshold.setValue(90)
        threshold_row.addWidget(self.threshold)
        self.threshold_save = QPushButton("이 항목에 기준 적용")
        self.threshold_save.clicked.connect(self.save_threshold)
        threshold_row.addWidget(self.threshold_save)
        recognition.addLayout(threshold_row)
        recognition.addWidget(QLabel("기본 90% · 낮출수록 다른 버튼도 잡힐 수 있습니다. 잘못된 화면에서도 인식되는지 확인하세요."))
        setup.addWidget(QLabel("초록: 클릭 대상 / 파랑: 확인 이미지 / 노랑: 검색 범위 (클릭 안 함)"))
        recognition.addWidget(QLabel("유사도 기준은 항목별 저장입니다. 새 이미지의 기준은 기본 90%, 변경은 이 탭에서 적용하세요."))
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
        actions_panel.addWidget(QLabel("먼저 ②에서 인식 결과를 확인하세요. 이 탭은 실제 키·마우스를 1회 조작합니다."))
        actions_panel.addWidget(self.action_enabled)
        actions = QHBoxLayout()
        self.action_choice = QComboBox()
        for key, label, _ in NAVIGATION_STEPS:
            self.action_choice.addItem(label, key)
            self.action_choice.setItemData(self.action_choice.count() - 1, label + "\n이 동작 하나만 실행합니다. 다음 번호로 자동 진행하지 않습니다.", Qt.ItemDataRole.ToolTipRole)
        actions.addWidget(self.action_choice, 1)
        action_button = QPushButton("선택 동작 1회 실행 (3초 후 · F9 중지)")
        action_button.clicked.connect(self.start_action)
        actions.addWidget(action_button)
        actions_panel.addLayout(actions)
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
        review_panel.addWidget(QLabel("이미지, 검색 범위, 비용, 수량을 확인한 뒤 검토 완료를 표시하세요. 변경 시 검토 표시는 해제됩니다."))
        review_panel.addWidget(review)
        tips = {
            self.kind: "보정 항목을 필터링합니다. 처음에는 순서대로 전체를 선택하세요. 보정 번호와 동작 테스트 번호는 서로 다릅니다.",
            help_button: "선택한 항목의 설명을 클릭해서 계속 볼 수 있습니다. 목록이나 버튼에 마우스를 올려도 설명이 나타납니다.",
            capture: "프로그램 창을 숨기고 3초 뒤 촬영합니다. 그동안 안내된 게임 화면을 준비하세요. 같은 화면의 다른 항목은 이 캡처를 재사용합니다.",
            restart: "현재 항목의 저장 전 선택을 취소하고 대상을 다시 고릅니다. 기존에 저장한 파일은 삭제하지 않습니다.",
            previous: "이전 보정 항목으로 이동합니다. 저장하지 않은 선택은 취소됩니다. 이전 캡처가 있으면 재사용합니다.",
            following: "다음 보정 항목으로 이동합니다. 현재 선택을 저장하지는 않습니다. 저장하려면 보정 탭의 저장 버튼을 누르세요.",
            selected_test: "선택한 항목을 현재 게임 화면에서 찾아 위치·유사도를 표시합니다. 3초 안에 게임을 활성화하세요. 클릭·구매·분해는 하지 않습니다.",
            stage_test: "현재 보정 화면 단계에 속한 항목들을 함께 검사합니다. 다른 단계로 자동 이동하거나 게임을 조작하지 않습니다.",
            self.threshold: "선택한 이미지의 통과 기준입니다. 50~100%, 새 이미지 기본 90%. 예: 80%면 80% 이상을 일치로 봅니다. 정답 확률은 아니며 낮추면 오인식이 늘 수 있습니다.",
            self.threshold_save: "현재 항목의 유사도 기준만 저장합니다. 모든 항목에 적용하지 않습니다. 변경 후 최종 검토 표시는 해제됩니다.",
            self.saved_preview: "이미 저장된 비교용 이미지입니다. 현재 드래그 중인 선택과 다를 수 있습니다. 원본 보기로 실제 저장 범위를 확인하세요.",
            enlarge: "저장된 PNG를 원본 크기로 확인합니다. 검색 영역 항목은 좌표만 저장하므로 이미지가 없습니다.",
            self.action_enabled: "체크하면 선택 동작 테스트에서 실제 키보드·마우스 입력을 허용합니다. 매 테스트 종료 후 해제됩니다.",
            action_button: "선택한 동작 하나만 실행합니다. 3초 안에 게임과 시작 화면을 준비하세요. 다음 동작은 자동 실행하지 않습니다. F9로 중지합니다.",
            review: "수량·비용·이미지·검색 범위를 직접 확인했다는 표시입니다. 실게임 성공을 자동 검증하지 않습니다. 보정이나 유사도를 변경하면 해제됩니다.",
        }
        for widget, text in tips.items():
            widget.setToolTip(text)
            widget.setToolTipDuration(20000)
        for index, text in enumerate((
                "화면 캡처 → 대상 이미지 선택 → 검색 범위 지정 → 저장 순서입니다. 이 탭에서는 게임을 클릭하지 않습니다.",
                "현재 화면에서 인식 위치와 유사도를 확인하고 항목별 기준을 설정합니다. 실제 입력은 없습니다.",
                "선택한 키·클릭 동작 하나를 실행합니다. 구매 확정·분해 실행은 포함하지 않습니다.",
                "저장한 보정과 테스트 결과를 확인한 뒤 검토 완료를 표시합니다.")):
            self.tabs.setTabToolTip(index, text)
        self.action_choice.currentIndexChanged.connect(self.update_action_help)
        self.update_action_help()
        self.kind.currentIndexChanged.connect(self.fill_names)
        self.fill_names()
        self.tabs.currentChanged.connect(self.change_tab)
        self.change_tab(0)

    def update_action_help(self):
        key = self.action_choice.currentData()
        definition = next(item for item in NAVIGATION_STEPS if item[0] == key)
        text = definition[1] + "\n필요한 보정: " + ", ".join(korean_label(name) for name in definition[2])
        text += "\n선택한 동작만 실행합니다. 보정 목록의 번호와는 다릅니다."
        self.action_choice.setToolTip(text)

    def change_tab(self, index):
        self.test_results.setVisible(index in (1, 2))
        self.scroll.setVisible(index != 3)
        if index == 0:
            self.show_help()

    def fill_names(self):
        self.name.clear()
        for number, (name, stage, _) in enumerate(capture_steps(self.config.quantity), 1):
            if self.kind.currentIndex() == 1 and is_region(name):
                continue
            if self.kind.currentIndex() == 2 and not is_region(name):
                continue
            self.name.addItem(f"{number:02d}. [{stage}] [{target_role(name)}] {korean_label(name)}", name)
            self.name.setItemData(self.name.count() - 1, item_tooltip(name), Qt.ItemDataRole.ToolTipRole)
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
        self.pending_crop = None
        self.name.setToolTip(item_tooltip(name))
        self.stage_text.setText(f"현재 화면: {stage}\n{instructions}")
        self.save_button.setText("검색 영역 저장 → 다음 항목" if is_region(name) else "① 대상 선택 완료 → 검색 범위")
        self.save_button.setToolTip("검색할 범위의 좌표만 저장합니다. 이미지 파일은 만들지 않습니다." if is_region(name) else "먼저 비교할 이미지 하나를 드래그하세요. 이 버튼을 누르면 같은 캡처에서 검색 범위를 지정합니다. 아직 파일은 저장하지 않습니다.")
        self.threshold.setEnabled(not is_region(name))
        self.threshold_save.setEnabled(not is_region(name))
        self.threshold.setValue(self.data.get("templates", {}).get(name, {}).get("threshold", .90) * 100)
        if self.capture_stage != stage:
            self.capture_stage = None
            if stage in self.stage_frames:
                self.install_capture(self.stage_frames[stage], stage)
            else:
                self.view = None
                widget = self.scroll.takeWidget()
                if widget:
                    widget.deleteLater()
        if self.capture_stage == stage:
            self.stage_text.setText(f"현재 화면: {stage} · 캡처 재사용 중 (화면이 바뀌었다면 다시 캡처)\n{instructions}")
        else:
            self.stage_text.setText(f"현재 화면: {stage} · 새 캡처 필요\n{instructions}")
        if self.view is not None:
            self.view.rect = QRect()
            self.view.overlays = []
            self.view.click_point = None
            self.view.selection_color = Qt.GlobalColor.yellow if is_region(name) else Qt.GlobalColor.green if name in CLICK_TARGETS else Qt.GlobalColor.cyan
            self.view.update()
        if name == "shop_target":
            hint = "버들잎 면갑의 아이콘·이름·파란 등급이 함께 보이는 상점 항목을 선택하세요. 별도 툴팁 캡처는 필요 없습니다."
        elif name == "buy_button":
            hint = "파란 버들잎 면갑과 같은 줄의 구매 버튼 하나만 글자·테두리까지 감싸세요. 다른 구매 버튼과 배경은 제외하고 마우스는 버튼에서 떼세요."
        elif name == "quantity_field":
            hint = "숫자를 입력하는 칸 전체를 테두리까지 선택하세요. 수량 입력 시 이 칸의 오른쪽 부분을 클릭합니다."
        elif is_region(name):
            hint = "아이템을 검사할 영역 전체를 드래그하세요. 분해 칸은 한 칸씩 따로 지정합니다."
        elif name in ("buy_button", "buy_confirm", "dismantle_button", "complete_confirm", "page_two", "shop_menu", "dismantle_icon"):
            hint = "이 버튼의 글자·아이콘과 테두리가 들어가도록 드래그하세요. 일치한 이미지의 가운데를 클릭합니다."
        elif "cost_" in name or name.startswith("quantity_"):
            hint = "숫자 일부만 자르지 말고 통화 표시 또는 입력칸 테두리까지 포함해 전체 값을 선택하세요."
        else:
            hint = "해당 글자·아이콘이 선명하게 들어가도록 드래그하세요. 화면이 바뀌면 게임 캡처를 다시 누르세요."
        saved = name in self.data["regions" if is_region(name) else "templates"]
        self.help_text.setText(f"[{target_role(name)}] {'저장됨' if saved else '미저장'} · {hint}")
        self.help_text.setToolTip(item_tooltip(name))
        if self.view is not None:
            self.view.setToolTip(item_tooltip(name) + "\n마우스로 드래그하여 선택하세요. 여기서는 실제 게임을 클릭하지 않습니다.")
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
            spec = self.data["templates"][name]
            self.preview_details.setText(f"{target_role(name)} · {path.name}\n원본 {pixmap.width()}×{pixmap.height()} 픽셀\n검색 범위 {spec['roi']} · 기준 {spec.get('threshold', .97) * 100:g}%")
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
            profile = Profile(self.path, self.config.resolution)
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
                self.tabs.setCurrentIndex(0)
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
        self.capture_stage = None
        self.pending_crop = None
        self.view = CropView(frame)
        self.view.selected.connect(lambda r: self.status.setText(f"선택: x={r.x()}, y={r.y()}, w={r.width()}, h={r.height()}"))
        self.scroll.setWidget(self.view)

    def finish_action(self):
        self.action_enabled.setChecked(False)
        self.restore_test_windows()
        self.status.setText("동작 테스트 종료. 결과를 확인한 뒤 다음 동작을 직접 선택하세요.")
        if self.close_after_action:
            self.reject()

    def current_stage(self):
        return next((stage for name, stage, _ in capture_steps(self.config.quantity)
                     if name == self.name.currentData()), None)

    def install_capture(self, frame, stage):
        self.capture_stage = stage
        self.pending_crop = None
        self.view = CropView(frame)
        self.view.selected.connect(self.selection_changed)
        self.scroll.setWidget(self.view)

    def selection_changed(self, rect):
        self.status.setText(f"선택: x={rect.x()}, y={rect.y()}, w={rect.width()}, h={rect.height()}")
        if self.pending_crop is None and self.name.currentData() in CLICK_TARGETS:
            self.view.click_point = rect.center()
            self.view.update()

    def save_threshold(self):
        name = self.name.currentData()
        spec = self.data.get("templates", {}).get(name)
        if not spec:
            QMessageBox.information(self, "먼저 보정", "① 캡처·보정에서 대상 이미지와 검색 범위를 먼저 저장하세요.")
            return
        spec["threshold"] = self.threshold.value() / 100
        self.data["reviewed_quantities"] = []
        write_json(self.path, self.data)
        self.update_saved_preview()
        self.status.setText(f"{korean_label(name)} 기준 {self.threshold.value():g}% 저장. ②에서 인식을 다시 확인하세요.")

    def capture(self):
        if self.test_timer.isActive() or self.capture_timer.isActive() or (self.action_worker and self.action_worker.isRunning()):
            return
        self.restore_parent = bool(self.parentWidget() and self.parentWidget().isVisible())
        self.hide()
        if self.restore_parent:
            self.parentWidget().hide()
        self.capture_timer.start(3000)

    def capture_now(self):
        capture = None
        try:
            capture = ScreenCapture(GameWindow(self.config.window_title, self.config.resolution))
            frame = capture.capture(foreground=False)
            stage = self.current_stage()
            self.stage_frames[stage] = frame
            self.install_capture(frame, stage)
            self.show_help()
            self.status.setText("캡처 완료. 같은 화면의 항목은 재촬영 없이 계속 지정하세요.")
        except Exception as error:
            QMessageBox.warning(self, "캡처 실패", str(error))
        finally:
            if capture:
                capture.close()
            self.restore_test_windows()

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
            profile = Profile(self.path, self.config.resolution)
            # No full-profile validation: unfinished stages may be tested separately.
            names = [name for name in self.test_names if not is_region(name) and name in profile.templates]
            capture = ScreenCapture(GameWindow(self.config.window_title, self.config.resolution))
            frame = capture.capture(foreground=True)
            detector = Detector(profile, names=names)
            for name in self.test_names:
                label = korean_label(name)
                if is_region(name):
                    region = profile.regions.get(name)
                    if valid_rect(region, self.config.resolution):
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
            self.capture_stage = None
            self.pending_crop = None
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
        self.capture_timer.stop()
        if self.restore_parent and self.parentWidget():
            self.parentWidget().showNormal()
        self.restore_parent = False
        super().reject()

    def save_crop(self):
        name = self.name.currentData()
        if self.view is None or self.capture_stage != self.current_stage():
            QMessageBox.information(self, "캡처 필요", "현재 단계의 게임 화면을 먼저 캡처하세요.")
            return
        if min(self.view.rect.width(), self.view.rect.height()) < 5:
            QMessageBox.warning(self, "선택 필요", "화면에서 5×5 픽셀 이상의 대상을 드래그하세요.")
            return
        rect = QRect(self.view.rect)
        if not is_region(name) and self.pending_crop is None:
            self.pending_crop = rect
            search = rect.adjusted(-12, -12, 12, 12).intersected(self.view.rect_for_frame())
            if name.startswith("inventory_target_"):
                search = self.view.rect_for_frame()
            self.view.overlays = [(rect, target_role(name), Qt.GlobalColor.green if name in CLICK_TARGETS else Qt.GlobalColor.cyan)]
            self.view.rect = search
            self.view.selection_color = Qt.GlobalColor.yellow
            self.view.click_point = rect.center() if name in CLICK_TARGETS else None
            self.view.update()
            self.save_button.setText("② 검색 범위 확인·저장 → 다음 항목")
            self.save_button.setToolTip("대상 이미지와 노란 검색 범위를 함께 저장합니다. 검색 범위는 대상 전체를 포함해야 합니다. 저장 후 다음 보정 항목으로 이동합니다.")
            hint = "노란 사각형 안에서만 위 이미지를 찾습니다. 대상을 포함하되 같은 버튼이 여러 개 들어가지 않게 드래그하세요. 기본 범위를 그대로 저장해도 됩니다."
            if name in ("inventory_target", "slot_empty", "slot_target"):
                hint += " 이 이미지는 자동 실행 시 별도로 지정한 인벤토리/분해 칸 검색 영역에서 검사합니다."
            self.help_text.setText("[검색 범위 · 클릭 안 함] " + hint)
            self.help_text.setToolTip(hint)
            self.view.setToolTip(hint)
            self.status.setText("대상 선택 완료. 같은 캡처에서 검색 범위를 확인하세요. 아직 파일은 저장하지 않았습니다.")
            return
        roi = [rect.x(), rect.y(), rect.width(), rect.height()]
        if not is_region(name):
            target = self.pending_crop
            if not rect.contains(target):
                QMessageBox.warning(self, "검색 범위 확인", "검색 범위는 앞서 선택한 대상 이미지 전체를 포함해야 합니다.")
                return
            x, y, w, h = target.x(), target.y(), target.width(), target.height()
            crop = self.view.frame[y:y+h, x:x+w]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            ok, encoded = cv2.imencode(".png", crop)
            if not ok:
                raise RuntimeError("PNG 저장 실패")
            encoded.tofile(str(self.path.parent / (name + ".png")))
            self.data["templates"][name] = {
                "file": name + ".png", "roi": roi, "threshold": self.threshold.value() / 100,
                "crop": [x, y, w, h],
            }
        else:
            self.data["regions"][name] = roi
        self.data["reviewed_quantities"] = []
        write_json(self.path, self.data)
        self.pending_crop = None
        self.status.setText(korean_label(name) + " 저장 완료. 같은 화면은 재사용하며, 화면이 바뀌는 단계에서만 캡처하세요.")
        if self.name.currentIndex() < self.name.count() - 1:
            self.move_item(1)
        else:
            self.show_help()
            self.tabs.setCurrentIndex(1)
            self.status.setText("마지막 항목 저장 완료. ② 인식 확인에서 저장 결과와 유사도를 확인하세요.")

    def review(self):
        try:
            profile = Profile(self.path, self.config.resolution)
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
