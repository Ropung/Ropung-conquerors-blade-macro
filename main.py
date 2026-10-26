import sys


def main():
    # DPI awareness must be set before Qt, MSS, or input modules initialize.
    from core.screen_capture import enable_dpi_awareness
    enable_dpi_awareness()
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
