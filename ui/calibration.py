import json
from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QComboBox, QMessageBox, QScrollArea)

from core.config import write_json
from core.image_detector import Detector, Profile, required_templates
from core.screen_capture import GameWindow, ScreenCapture
from core.state_machine import batches


LABELS = {
    "npc_ready": "NPC 상호작용 안내 (F키 표시)",
    "shop_menu": "NPC 메뉴의 마구 상점 항목",
    "shop_open": "마구 상점이 열린 화면의 고정 표시",
    "page_two": "상점 2페이지 이동 버튼",
    "page_two_active": "상점 2페이지 선택 표시",
    "shop_target": "상점의 버들잎 면갑 아이콘",
    "shop_target_identity": "상점 툴팁의 버들잎 면갑 이름 + 파란 등급",
    "buy_button": "상점 구매 버튼",
    "buy_popup": "구매 수량 창의 고정 제목/표시",
    "quantity_field": "구매 수량 입력칸",
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
        ("NPC 앞", "상인 바로 앞에서 F키 안내가 보이는 화면을 캡처하세요.", ["npc_ready"]),
        ("NPC 메뉴", "게임에서 F키를 누른 뒤 NPC 메뉴를 캡처하세요.", ["shop_menu"]),
        ("상점", "마구 상점을 클릭해 들어간 화면을 캡처하세요.", ["shop_open", "page_two"]),
        ("상점 2페이지", "2페이지로 이동한 화면을 캡처하세요.", ["page_two_active", "shop_target", "buy_button"]),
        ("상점 아이템 설명", "버들잎 면갑에 마우스를 올리고, 이름과 파란 등급 표시가 모두 들어가도록 한 번에 선택해 저장하세요.", ["shop_target_identity"]),
        ("구매 수량 창", f"구매 버튼을 누르고 수량을 {quantity}개로 입력한 화면을 캡처하세요. 최종 구매는 아직 누르지 마세요.",
         ["buy_popup", "quantity_field", f"quantity_{quantity}", "buy_target_name", "buy_target_blue", f"buy_cost_{quantity * 1600}", "buy_confirm"]),
        ("인벤토리", "상점을 닫고 I키로 인벤토리를 연 화면을 캡처하세요.", ["inventory_open", "dismantle_icon"]),
        ("빈 분해 창", "왼쪽 네 번째 분해 아이콘을 누르고, 분해 칸이 모두 빈 화면을 캡처하세요.",
         ["dismantle_panel", "inventory", "slot_empty", *[f"slot_{i}" for i in range(15)]]),
        ("인벤토리 대상", "인벤토리에 버들잎 면갑이 있는 화면을 캡처하세요.", ["inventory_target"]),
        ("인벤토리 아이템 설명", "인벤토리의 버들잎 면갑에 마우스를 올려 설명이 보이게 한 뒤 캡처하세요.", ["inventory_target_name", "inventory_target_blue"]),
        ("분해 등록", "대상만 분해 칸에 등록한 화면을 캡처하세요. 분해 실행 버튼은 아직 누르지 마세요.", ["slot_target", "dismantle_button"]),
    ]
    for amount in dict.fromkeys(batches(quantity)):
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


class CalibrationDialog(QDialog):
    def __init__(self, config, root, parent=None):
        super().__init__(parent)
        self.config, self.root = config, root
        self.path = root / config.profile
        self.data = (json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists()
                     else {"resolution": [2560, 1440], "templates": {}, "regions": {}, "reviewed_quantities": []})
        self.view = None
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
        self.stage_text = QLabel()
        self.stage_text.setWordWrap(True)
        layout.addWidget(self.stage_text)
        self.help_text = QLabel()
        self.help_text.setWordWrap(True)
        layout.addWidget(self.help_text)
        self.name.currentIndexChanged.connect(self.show_help)
        self.status = QLabel("캡처 대기")
        layout.addWidget(self.status)
        self.scroll = QScrollArea()
        layout.addWidget(self.scroll, 1)
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
            return
        _, stage, instructions = next(step for step in capture_steps(self.config.quantity) if step[0] == name)
        self.stage_text.setText(f"현재 단계: {stage}\n{instructions}")
        if self.view is not None:
            self.view.rect = QRect()
            self.view.update()
        if name == "shop_target_identity":
            hint = "버들잎 면갑 이름과 파란 등급을 함께 포함하세요. 수량·능력치 등 변하는 정보는 제외하세요."
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
            self.data["templates"][name] = {"file": name + ".png", "roi": search, "threshold": .97}
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
