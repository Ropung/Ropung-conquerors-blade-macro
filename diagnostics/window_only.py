"""Startup probe. Does not inspect or control any other window."""
import sys
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget


def main(label="01 - Window only"):
    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("Startup diagnostic")
    window.resize(520, 220)
    layout = QVBoxLayout(window)
    layout.addWidget(QLabel(label + "\nWindow opened successfully.\nNo screenshots, hotkeys or input events are used."))
    close = QPushButton("Close")
    close.setMinimumHeight(60)
    close.clicked.connect(window.close)
    layout.addWidget(close)
    window.show()
    if "--smoke" in sys.argv:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
