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


LABELS = {
    "npc_ready": "NPC 상호작용 안내 (F키 표시)",
    "shop_menu": "NPC 메뉴의 마구 상점 항목",
    "shop_open": "마구 상점이 열린 화면의 고정 표시",
    "page_two": "상점 2페이지 이동 버튼",
    "page_two_active": "상점 2페이지 선택 표시",
    "shop_target": "상점의 버들잎 면갑 아이콘",
    "shop_target_name": "상점 툴팁의 버들잎 면갑 이름",
    "shop_target_blue": "상점 툴팁의 파란 등급 표시",
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
        self.kind.addItems(["찾을 이미지 (버튼·글자·아이콘)", "검색 영역 (인벤토리·분해 칸)"])
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
        names = (required_templates(self.config.quantity) if self.kind.currentIndex() == 0
                 else ["inventory", *[f"slot_{i}" for i in range(15)]])
        for name in names:
            self.name.addItem(korean_label(name), name)
        self.show_help()

    def show_help(self):
        name = self.name.currentData()
        if not name:
            self.help_text.clear()
            return
        if self.kind.currentIndex() == 1:
            hint = "아이템을 검사할 영역 전체를 드래그하세요. 분해 칸은 한 칸씩 따로 지정합니다."
        elif name in ("buy_button", "buy_confirm", "dismantle_button", "complete_confirm", "page_two", "shop_menu", "dismantle_icon"):
            hint = "이 버튼의 글자·아이콘과 테두리가 들어가도록 드래그하세요. 일치한 이미지의 가운데를 클릭합니다."
        elif "cost_" in name or name.startswith("quantity_"):
            hint = "숫자 일부만 자르지 말고 통화 표시 또는 입력칸 테두리까지 포함해 전체 값을 선택하세요."
        else:
            hint = "해당 글자·아이콘이 선명하게 들어가도록 드래그하세요. 화면이 바뀌면 게임 캡처를 다시 누르세요."
        saved = name in self.data["templates" if self.kind.currentIndex() == 0 else "regions"]
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
        if self.kind.currentIndex() == 0:
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
        self.show_help()

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
