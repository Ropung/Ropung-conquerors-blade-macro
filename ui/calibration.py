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
        self.setWindowTitle("2560×1440 원본 캘리브레이션 (읽기 전용 캡처)")
        self.resize(1200, 850)
        layout = QVBoxLayout(self)
        info = QLabel("게임 UI를 수동으로 열고 [캡처] → 영역 드래그 → [저장]. 모든 좌표는 원본 픽셀입니다.\n"
                      "이름·등급은 shop/buy/inventory별로 저장하세요. 수량·비용은 전체 필드 테두리까지 잘라 숫자 일부 일치를 방지하세요.")
        info.setWordWrap(True)
        layout.addWidget(info)
        row = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItems(["템플릿", "영역"])
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
        self.name.addItems(required_templates(self.config.quantity) if self.kind.currentIndex() == 0
                           else ["inventory", *[f"slot_{i}" for i in range(15)]])

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
        name = self.name.currentText()
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
        self.status.setText(name + " 저장 완료. 변경으로 기존 검토 표시는 해제되었습니다.")

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
