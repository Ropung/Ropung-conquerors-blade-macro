from core.state_machine import SafetyError


class InputController:
    def __init__(self, window, control, enabled=False):
        import pyautogui
        self.backend = pyautogui
        self.backend.FAILSAFE = True
        self.backend.PAUSE = 0.05
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

    def move(self, point):
        x, y = point
        if not 0 <= x < 2560 or not 0 <= y < 1440:
            raise SafetyError("게임 영역 밖 입력 거부")
        left, top = self.window.origin
        self._perform(self.backend.moveTo, left + x, top + y)

    def click(self, point, button="left"):
        self.move(point)
        self._perform(self.backend.click, button=button)

    def key(self, key):
        self._perform(self.backend.press, key)

    def quantity(self, number):
        self._perform(self.backend.hotkey, "ctrl", "a")
        self._perform(self.backend.write, str(number), interval=.08)
