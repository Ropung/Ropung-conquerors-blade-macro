import time
import json

from automation.dismantle_automation import dismantle
from automation.inventory_automation import open_inventory, register, slots, targets
from automation.shop_automation import purchase
from automation.npc_interaction import open_shop
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
        last_frame = None
        while remaining > 0:
            self.control.checkpoint()
            start = time.monotonic()
            frame = self.frame()
            last_frame = frame
            stable = stable + 1 if self.detector.present(frame, name) else 0
            if stable >= 2:
                return frame
            remaining -= time.monotonic() - start
            self.control.delay(.1)
            remaining -= .1
        details = ""
        if last_frame is not None:
            try:
                import cv2
                report = self.detector.diagnose(last_frame, name)
                details = f" (최고 유사도 {report['similarity']:.1%}, 기준 {report['threshold']:.1%}, 검색 영역 {report['roi']})"
                folder = self.profile.path.parent.parent / "logs"
                folder.mkdir(parents=True, exist_ok=True)
                ok, encoded = cv2.imencode(".png", last_frame)
                if ok:
                    encoded.tofile(str(folder / "last_failure.png"))
                (folder / "last_failure.json").write_text(json.dumps({"template": name, **report}, ensure_ascii=False, indent=2), encoding="utf-8")
                self.log("인식 실패 화면 저장: " + str(folder / "last_failure.png"))
            except Exception as error:
                self.log("인식 실패 진단 저장 오류: " + str(error))
        raise SafetyError("화면 확인 시간 초과: " + name + details)

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

    def close_ui(self, marker):
        self.require(self.frame(), marker)
        self.inputs.key("esc")
        self.wait_absent(marker)

    def hover_target(self, name):
        point = self.detector.one(self.frame(), name)
        self.inputs.move(point)
        self.control.delay(.4)
        # The saved item row includes its name and blue grade; no extra tooltip crop.
        self.require(self.frame(), name)


def run(config, root, control, log, change_state, single_cycle=False):
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
        # First game input is F; only the resulting NPC menu must be recognized.
        open_shop(session)
        session.close_ui("shop_open")
        # Abort when a target already exists. This establishes purchase provenance.
        open_inventory(session)
        slots(session, 0)
        targets(session, 0)
        session.close_ui("inventory_open")
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
            session.close_ui("inventory_open")
            cycle += 1
            log(f"반복 {cycle}회 완료 / {config.quantity}개 구매·분해")
            if single_cycle:
                log("1회 테스트 완료. 추가 구매 없이 자동 중지합니다.")
                return
    finally:
        capture.close()


def required_now(profile):
    return sorted(set(profile.templates) - {"slot_target", "slot_empty"})


def run_dismantle_once(config, root, control, log, change_state):
    """Test the already-owned items, with no NPC interaction or purchase."""
    quantity = config.quantity
    if not config.live_input or type(quantity) is not int or not 1 <= quantity <= 15:
        raise SafetyError("실제 입력 활성화 및 1~15개 수량 설정이 필요합니다.")
    names = {"dismantle_panel", "inventory_target", "slot_target", "slot_empty",
             "inventory_target_name", "inventory_target_blue", "dismantle_button",
             "complete_popup", "complete_confirm", f"dismantle_cost_{quantity * 300}"}
    profile = Profile(root / config.profile)
    profile.templates = {name: spec for name, spec in profile.templates.items() if name in names}
    profile.validate(quantity, template_names=names)
    Detector(profile)
    log(f"3초 후 기존 버들잎 면갑 {quantity}개 분해 테스트. 게임의 분해 창을 활성화하세요. F9 중지.")
    control.delay(3)
    window = GameWindow(config.window_title)
    window.check()
    capture = ScreenCapture(window)
    try:
        session = Session(config, profile, capture, InputController(window, control, enabled=True), control, log)
        session.expect("dismantle_panel")
        try:
            slots(session, quantity)
        except SafetyError:
            # Only accept all-empty or exactly the requested target count.
            slots(session, 0)
            targets(session, quantity)
            change_state(State.REGISTERING)
            register(session, quantity, quantity)
        else:
            targets(session, 0)
        change_state(State.DISMANTLING)
        dismantle(session, quantity, 0)
        log(f"기존 대상 {quantity}개 분해 테스트 완료. 구매·재반복 없이 중지합니다.")
    finally:
        capture.close()
