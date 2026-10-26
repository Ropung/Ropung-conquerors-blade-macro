import ctypes
from ctypes import wintypes
import sys

from core.state_machine import SafetyError


def enable_dpi_awareness():
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            ctypes.windll.shcore.SetProcessDpiAwareness(2)


class GameWindow:
    def __init__(self, title):
        if sys.platform != "win32":
            raise SafetyError("Windows에서만 실행할 수 있습니다.")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        u = self.user32
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsIconic.argtypes = [wintypes.HWND]
        u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.IsWindow.argtypes = [wintypes.HWND]
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        matches = []

        def visit(hwnd, _):
            length = u.GetWindowTextLengthW(hwnd)
            text = ctypes.create_unicode_buffer(length + 1)
            u.GetWindowTextW(hwnd, text, length + 1)
            if text.value == title and u.IsWindowVisible(hwnd):
                matches.append(hwnd)
            return True

        callback = callback_type(visit)
        u.EnumWindows(callback, 0)
        if len(matches) != 1:
            raise SafetyError(f"정확한 게임 제목 '{title}' 창이 하나여야 합니다: {len(matches)}개")
        self.hwnd = matches[0]
        self.origin = None

    def activate(self):
        if self.user32.IsIconic(self.hwnd):
            raise SafetyError("게임 최소화를 먼저 해제하세요.")
        self.user32.SetForegroundWindow(self.hwnd)
        self.check()

    def check(self, foreground=True):
        u = self.user32
        if not u.IsWindow(self.hwnd) or u.IsIconic(self.hwnd):
            raise SafetyError("게임 창이 사라졌거나 최소화되었습니다.")
        if foreground and u.GetForegroundWindow() != self.hwnd:
            raise SafetyError("게임이 활성 창이 아니므로 중지합니다.")
        rect, outer, point = wintypes.RECT(), wintypes.RECT(), wintypes.POINT(0, 0)
        if not u.GetClientRect(self.hwnd, ctypes.byref(rect)) or not u.ClientToScreen(self.hwnd, ctypes.byref(point)):
            raise SafetyError("게임 창 좌표를 가져오지 못했습니다.")
        u.GetWindowRect(self.hwnd, ctypes.byref(outer))
        if (rect.right, rect.bottom) != (2560, 1440):
            raise SafetyError(f"2560×1440 필요: 현재 {rect.right}×{rect.bottom}")
        if (outer.left, outer.top, outer.right, outer.bottom) != (point.x, point.y, point.x + 2560, point.y + 1440):
            raise SafetyError("테두리 없는 전체 창 모드를 확인하세요.")
        current = (point.x, point.y)
        if self.origin is not None and self.origin != current:
            raise SafetyError("게임 위치가 변경되었습니다. 다시 시작하세요.")
        self.origin = current
        return {"left": point.x, "top": point.y, "width": 2560, "height": 1440}


class ScreenCapture:
    def __init__(self, window):
        import mss
        self.window = window
        # Construct MSS in the same thread that captures.
        self.grabber = mss.mss()

    def capture(self, foreground=True):
        import numpy as np
        frame = np.array(self.grabber.grab(self.window.check(foreground)))[:, :, :3].copy()
        # Sample the whole image on a regular grid instead of calculating
        # variance over eleven million channels for every registration check.
        if frame.shape != (1440, 2560, 3) or frame[::16, ::16].std() < 2:
            raise SafetyError("화면 캡처가 비어 있거나 잘못되었습니다.")
        return frame

    def close(self):
        self.grabber.close()
