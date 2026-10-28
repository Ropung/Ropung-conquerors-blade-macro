import time
import json
from core.config import profile_path, app_root
from core.run_stats import next_quantity

from automation.dismantle_automation import dismantle
from automation.inventory_automation import open_inventory, register, slots, targets, slot_count
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
            try:
                self.detector.one(frame, name)
            except SafetyError:
                self.save_failure(frame, name)
                raise

    def save_failure(self, frame, name):
        try:
            import cv2
            report = self.detector.diagnose(frame, name)
            folder = app_root() / "logs"
            folder.mkdir(parents=True, exist_ok=True)
            ok, encoded = cv2.imencode(".png", frame)
            if ok:
                encoded.tofile(str(folder / "last_failure.png"))
            (folder / "last_failure.json").write_text(json.dumps({"template": name, **report}, ensure_ascii=False, indent=2), encoding="utf-8")
            self.log(f"인식 실패 {name}: 유사도 {report['similarity']:.1%} / 기준 {report['threshold']:.1%} · logs/last_failure.png 저장")
        except Exception as error:
            self.log("인식 실패 진단 저장 오류: " + str(error))

    def expect_all(self, names, timeout=3):
        remaining = timeout
        while remaining > 0:
            frame = self.frame()
            if all(self.detector.present(frame, name) for name in names):
                return frame
            self.control.delay(.15)
            remaining -= .15
        self.require(frame, *names)

    def expect(self, name, timeout=None):
        self.log("화면 확인: " + name)
        remaining = timeout or self.config.timeout_seconds
        stable = 0
        last_frame = None
        last_notice = time.monotonic()
        while remaining > 0:
            self.control.checkpoint()
            start = time.monotonic()
            frame = self.frame()
            last_frame = frame
            stable = stable + 1 if self.detector.present(frame, name) else 0
            if stable >= 2:
                return frame
            if time.monotonic() - last_notice >= 2:
                self.log(f"화면 대기 중: {name} · 제한 시간 약 {max(0, remaining):.0f}초 남음")
                last_notice = time.monotonic()
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
        if name == "shop_menu":
            self.log("마구상점 메뉴 표시 확인 · 클릭 준비 0.7초 대기")
            self.control.delay(.7)
            for attempt in range(3):
                frame = self.frame()
                if self.detector.present(frame, after):
                    return
                self.inputs.click_ui(self.detector.one(frame, name))
                try:
                    self.expect(after, timeout=2)
                    return
                except SafetyError as error:
                    if not str(error).startswith("화면 확인 시간 초과:") or attempt == 2:
                        raise
                    # Recheck the visible menu before every subsequent click;
                    # foreground/stop/ambiguous-image errors are never retried.
                    self.log("마구상점 메뉴가 남아 있음 · 클릭 재시도")
            return
        frame = self.expect(name, timeout=3) if name == "page_two" else self.frame()
        point = self.detector.one(frame, name)
        if name == "quantity_field":
            # Click inside the right end of the textbox so the caret follows 1.
            # Arrow keys can move focus to the adjacent plus button in this UI.
            width = self.detector.images[name].shape[1]
            self.inputs.click_ui((point[0] + width // 3, point[1]))
        else:
            self.inputs.click(point)
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
        frame = self.expect(name, timeout=3)
        point = self.detector.one(frame, name)
        self.inputs.move(point)
        self.control.delay(.4)
        # The saved item row includes its name and blue grade; no extra tooltip crop.
        self.expect_all((name,), timeout=3)


def run(config, root, control, log, change_state, single_cycle=False, max_dismantle=0):
    config.validate()
    if type(max_dismantle) is not int or max_dismantle < 0:
        raise SafetyError("최대 분해 개수는 0 이상의 정수여야 합니다.")
    change_state(State.CHECKING)
    profile = Profile(profile_path(config, root), config.resolution)
    profile.apply_similarity(config.similarity)
    profile.validate(config.quantity)
    first_quantity = next_quantity(config.quantity, max_dismantle, 0)
    planned = {first_quantity}
    if not single_cycle:
        planned.add(config.quantity)
        if max_dismantle and max_dismantle % config.quantity:
            planned.add(max_dismantle % config.quantity)
    if config.live_input:
        for quantity in planned:
            profile.validate(quantity)
            if quantity not in profile.data.get("reviewed_quantities", []):
                raise SafetyError(f"제한 수량에 필요한 {quantity}개 구매·분해 보정 검토가 필요합니다.")
    # Load all images even in read-only mode; invalid files are a hard stop.
    Detector(profile)
    window = GameWindow(config.window_title, config.resolution)
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
        # purchase() starts directly with F and opens the NPC shop menu.
        # Verify the exact purchased quantity and empty dismantling slots below.
        cycle = 0
        completed = 0
        while True:
            control.checkpoint()
            quantity = next_quantity(config.quantity, max_dismantle, completed)
            if quantity == 0:
                log(f"최대 분해 개수 {max_dismantle}개 도달 · 자동 중지")
                return
            change_state(State.PURCHASING)
            purchase(session, quantity)
            open_inventory(session)
            targets(session, quantity)
            slots(session, 0)
            remaining = quantity
            for amount in batches(quantity):
                change_state(State.REGISTERING)
                register(session, amount, remaining)
                remaining -= amount
                change_state(State.DISMANTLING)
                dismantle(session, amount, remaining)
                completed += amount
            session.close_ui("inventory_open")
            cycle += 1
            log(f"반복 {cycle}회 완료 / 누적 {completed}개 분해" + (f" / 제한 {max_dismantle}개" if max_dismantle else ""))
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
             "inventory_target_identity", "dismantle_button",
             "complete_popup", "complete_confirm", "dismantle_cost_300", f"dismantle_cost_{quantity * 300}"}
    profile = Profile(profile_path(config, root), config.resolution)
    profile.apply_similarity(config.similarity)
    profile.templates = {name: spec for name, spec in profile.templates.items() if name in names}
    profile.validate(quantity, template_names=names)
    Detector(profile)
    log(f"3초 후 기존 버들잎 면갑 {quantity}개 분해 테스트. 게임의 분해 창을 활성화하세요. F9 중지.")
    control.delay(3)
    window = GameWindow(config.window_title, config.resolution)
    window.check()
    capture = ScreenCapture(window)
    try:
        session = Session(config, profile, capture, InputController(window, control, enabled=True), control, log)
        session.expect("dismantle_panel")
        registered = slot_count(session)
        if registered > quantity:
            raise SafetyError(f"등록된 대상 {registered}개가 설정 수량 {quantity}개보다 많습니다.")
        targets(session, quantity - registered)
        log(f"등록 상태 확인: {registered}/{quantity}개 · 인벤토리 {quantity - registered}개")
        if registered < quantity:
            change_state(State.REGISTERING)
            register(session, quantity - registered, quantity - registered, initial_count=registered)
        change_state(State.DISMANTLING)
        dismantle(session, quantity, 0)
        log(f"기존 대상 {quantity}개 분해 테스트 완료. 구매·재반복 없이 중지합니다.")
    finally:
        capture.close()
