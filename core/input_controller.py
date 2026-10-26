from core.state_machine import SafetyError
import logging


class InputController:
    def __init__(self, window, control, enabled=False):
        import pyautogui
        try:
            import pydirectinput
        except ImportError as error:
            raise SafetyError("게임 키 입력 모듈이 없습니다. .\\.venv\\Scripts\\python.exe -m pip install pydirectinput==1.0.4 실행 후 재시작하세요.") from error
        self.backend = pyautogui
        self.key_backend = pydirectinput
        self.backend.FAILSAFE = True
        self.backend.PAUSE = 0.05
        self.key_backend.FAILSAFE = True
        self.key_backend.PAUSE = 0.05
        self.window, self.control, self.enabled = window, control, enabled
        self.observation_revision = control.revision

    def _perform(self, operation, *args, **kwargs):
        self.control.checkpoint()
        self.window.check()
        if self.observation_revision != self.control.revision:
            raise SafetyError("일시정지 후 화면을 다시 확인해야 합니다. 현재 동작을 중지합니다.")
        if not self.enabled:
            raise SafetyError("실제 입력은 기본 비활성화 상태입니다.")
        operation(*args, **kwargs)
        self.control.checkpoint()
        self.window.check()

    def move(self, point, *, fast=False):
        x, y = point
        if not 0 <= x < 2560 or not 0 <= y < 1440:
            raise SafetyError("게임 영역 밖 입력 거부")
        left, top = self.window.origin
        options = {"_pause": False} if fast else {}
        self._perform(self.key_backend.moveTo, left + x, top + y, **options)
        logging.getLogger("macro").info("마우스 이동: 게임 좌표 %s, 화면 목표 %s, 실제 커서 %s", point, (left+x, top+y), self.key_backend.position())

    def click(self, point, button="left", *, positioned=False):
        if not positioned:
            self.move(point)
        # Let the game process the mouse-move/hover event before button-down.
        self.control.delay(.01 if positioned else .15)
        options = {"_pause": False} if positioned else {}
        def tap_mouse():
            try:
                self.key_backend.mouseDown(button=button, **options)
                self.control.delay(.035 if positioned else .12)
            finally:
                failsafe = self.key_backend.FAILSAFE
                try:
                    self.key_backend.FAILSAFE = False
                    self.key_backend.mouseUp(button=button, **options)
                finally:
                    self.key_backend.FAILSAFE = failsafe
        self._perform(tap_mouse)

    def key(self, key):
        # Give a game frame time to observe key-down; always release on stop/error.
        def tap():
            try:
                self.key_backend.keyDown(key)
                self.control.delay(.12)
            finally:
                # Releasing a held key must also work after a corner failsafe.
                failsafe = self.key_backend.FAILSAFE
                try:
                    self.key_backend.FAILSAFE = False
                    self.key_backend.keyUp(key)
                finally:
                    self.key_backend.FAILSAFE = failsafe
        self._perform(tap)

    def click_ui(self, point):
        """NPC menu clicks use Windows cursor placement and mouse events."""
        x, y = point
        if not 0 <= x < 2560 or not 0 <= y < 1440:
            raise SafetyError("게임 영역 밖 입력 거부")
        left, top = self.window.origin
        target = (left + x, top + y)
        self._perform(self.backend.moveTo, *target, duration=.12)
        # SetCursorPos can update the Windows cursor without updating the
        # game's hover state. Emit a tiny relative move inside the menu hitbox.
        self._perform(self.key_backend.moveRel, 1, 0, relative=True, _pause=False)
        self.control.delay(.08)
        self._perform(self.key_backend.moveRel, -1, 0, relative=True, _pause=False)
        self.control.delay(.3)
        def tap():
            actual = self.backend.position()
            if abs(actual[0] - target[0]) > 3 or abs(actual[1] - target[1]) > 3:
                raise SafetyError("메뉴 클릭 전 커서가 이동했습니다. 마우스를 움직이지 말고 다시 시작하세요.")
            logging.getLogger("macro").info("메뉴 Windows 클릭: 목표 %s / 실제 %s", target, actual)
            try:
                self.backend.mouseDown(button="left")
                self.control.delay(.18)
            finally:
                failsafe = self.backend.FAILSAFE
                try:
                    self.backend.FAILSAFE = False
                    self.backend.mouseUp(button="left")
                finally:
                    self.backend.FAILSAFE = failsafe
        self._perform(tap)

    def quantity(self, number):
        if type(number) is not int or not 1 <= number <= 20:
            raise SafetyError("구매 수량은 1~20이어야 합니다.")
        # Deleting this game's quantity restores its minimum of 1. Select the
        # existing digits and replace them, using the same scan-code input as F.
        self.key("home")
        def select_to_end():
            try:
                self.key_backend.keyDown("shift")
                self.key_backend.keyDown("end")
                self.control.delay(.08)
            finally:
                failsafe = self.key_backend.FAILSAFE
                try:
                    self.key_backend.FAILSAFE = False
                    self.key_backend.keyUp("end")
                    self.key_backend.keyUp("shift")
                finally:
                    self.key_backend.FAILSAFE = failsafe
        self._perform(select_to_end)
        for digit in str(number):
            self.key(digit)
