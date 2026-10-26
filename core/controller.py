import time

from automation.dismantle_automation import dismantle
from automation.inventory_automation import open_inventory, register, slots, targets
from automation.shop_automation import purchase
from core.image_detector import Detector, Profile
from core.input_controller import InputController
from core.screen_capture import GameWindow, ScreenCapture
from core.state_machine import SafetyError, State, batches


class Session:
    def __init__(self, config, profile, capture, inputs, control, log):
        self.config, self.profile = config, profile
        self.capture, self.inputs, self.control, self.log = capture, inputs, control, log
        self.detector = Detector(profile)

    def frame(self):
        while True:
            self.control.checkpoint()
            revision = self.control.revision
            frame = self.capture.capture()
            self.control.checkpoint()
            if revision == self.control.revision:
                self.inputs.observation_revision = revision
                return frame

    def require(self, frame, *names):
        for name in names:
            self.detector.one(frame, name)

    def expect(self, name, timeout=None):
        self.log("화면 확인: " + name)
        remaining = timeout or self.config.timeout_seconds
        stable = 0
        while remaining > 0:
            self.control.checkpoint()
            start = time.monotonic()
            frame = self.frame()
            stable = stable + 1 if self.detector.present(frame, name) else 0
            if stable >= 2:
                return frame
            remaining -= time.monotonic() - start
            self.control.delay(.1)
            remaining -= .1
        raise SafetyError("화면 확인 시간 초과: " + name)

    def wait_absent(self, name):
        remaining = self.config.timeout_seconds
        stable = 0
        while remaining > 0:
            frame = self.frame()
            stable = stable + 1 if not self.detector.present(frame, name) else 0
            if stable >= 2:
                return
            self.control.delay(.1)
            remaining -= .1
        raise SafetyError("팝업이 닫히지 않았습니다: " + name)

    def click(self, name, after):
        frame = self.frame()
        self.inputs.click(self.detector.one(frame, name))
        self.expect(after)

    def key(self, name, after):
        self.frame()
        self.inputs.key(name)
        self.expect(after)

    def hover_target(self, name):
        point = self.detector.one(self.frame(), name)
        self.inputs.move(point)
        self.control.delay(.4)
        self.require(self.frame(), "shop_target_name", "shop_target_blue")


def run(config, root, control, log, change_state):
    config.validate()
    change_state(State.CHECKING)
    profile = Profile(root / config.profile)
    profile.validate(config.quantity)
    # Load all images even in read-only mode; invalid files are a hard stop.
    Detector(profile)
    window = GameWindow(config.window_title)
    capture = ScreenCapture(window)
    try:
        if not config.live_input:
            # No focus changes, pointer movement, or simulated keys in diagnostics.
            frame = capture.capture(foreground=False)
            detector = Detector(profile)
            for name in required_now(profile):
                log(f"현재 화면 {name}: {len(detector.find_all(frame, name))}개")
            log("읽기 전용 진단 완료. 실제 입력 0회.")
            return
        if config.quantity not in profile.data.get("reviewed_quantities", []):
            raise SafetyError("이 수량의 캘리브레이션 검토가 필요합니다.")
        log("3초 후 게임 활성화. F9 중지 가능")
        control.delay(3)
        window.activate()
        inputs = InputController(window, control, enabled=True)
        session = Session(config, profile, capture, inputs, control, log)
        session.expect("npc_ready")
        # Abort when a target already exists. This establishes purchase provenance.
        open_inventory(session)
        slots(session, 0)
        targets(session, 0)
        session.key("esc", "npc_ready")
        cycle = 0
        while True:
            control.checkpoint()
            change_state(State.PURCHASING)
            purchase(session, config.quantity)
            open_inventory(session)
            targets(session, config.quantity)
            slots(session, 0)
            remaining = config.quantity
            for amount in batches(config.quantity):
                change_state(State.REGISTERING)
                register(session, amount, remaining)
                remaining -= amount
                change_state(State.DISMANTLING)
                dismantle(session, amount, remaining)
            session.key("esc", "npc_ready")
            cycle += 1
            log(f"반복 {cycle}회 완료 / {config.quantity}개 구매·분해")
    finally:
        capture.close()


def required_now(profile):
    return sorted(set(profile.templates) - {"slot_target", "slot_empty"})
