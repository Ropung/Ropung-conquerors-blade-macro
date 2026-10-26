"""Single navigation actions. Never confirms a purchase or dismantles an item."""
from core.controller import Session
from core.image_detector import Profile
from core.input_controller import InputController
from core.screen_capture import GameWindow, ScreenCapture
from core.state_machine import SafetyError
from automation.quantity_control import set_quantity


# key, label, necessary templates
NAVIGATION_STEPS = [
    ("npc", "1. F키 → 마구 상점 버튼 클릭", ["shop_menu", "shop_open"]),
    ("page", "2. 상점 2페이지로 이동", ["shop_open", "page_two", "page_two_active"]),
    ("hover", "3. 버들잎 면갑 항목 확인", ["page_two_active", "shop_target"]),
    ("select", "4. 버들잎 면갑 선택", ["page_two_active", "shop_target", "buy_button"]),
    ("popup", "5. 구매 수량 창 열기 (구매 확정 안 함)", ["shop_open", "buy_button", "buy_popup"]),
    ("quantity", "6. +/− 버튼으로 수량 설정 (구매 확정 안 함)", ["buy_popup", "quantity_plus", "quantity_minus", "buy_cost_1600"]),
    ("close_popup", "7. 구매 수량 창 닫기", ["buy_popup"]),
    ("close_shop", "8. 상점 닫기", ["shop_open"]),
    ("inventory", "9. I키 → 인벤토리 열기", ["inventory_open"]),
    ("panel", "10. 분해 창 열기 (분해 실행 안 함)", ["inventory_open", "dismantle_icon", "dismantle_panel"]),
]


def execute_step(session, key, quantity):
    if key == "npc":
        session.key("f", "shop_menu")
        session.click("shop_menu", "shop_open")
    elif key == "page":
        session.require(session.frame(), "shop_open")
        session.click("page_two", "page_two_active")
    elif key in ("hover", "select"):
        session.require(session.frame(), "page_two_active")
        session.hover_target("shop_target")
        if key == "select":
            session.click("shop_target", "buy_button")
    elif key == "popup":
        session.require(session.frame(), "shop_open")
        session.click("buy_button", "buy_popup")
    elif key == "quantity":
        session.require(session.frame(), "buy_popup")
        set_quantity(session, quantity)
    elif key == "close_popup":
        session.close_ui("buy_popup")
    elif key == "close_shop":
        session.close_ui("shop_open")
    elif key == "inventory":
        session.key("i", "inventory_open")
    elif key == "panel":
        session.require(session.frame(), "inventory_open")
        session.click("dismantle_icon", "dismantle_panel")
    else:
        raise SafetyError("사용할 수 없는 테스트 동작입니다.")


def run_step_test(config, root, control, key, log):
    definition = next((item for item in NAVIGATION_STEPS if item[0] == key), None)
    if definition is None:
        raise SafetyError("사용할 수 없는 테스트 동작입니다.")
    profile = Profile(root / config.profile)
    names = list(definition[2])
    if key == "quantity":
        if type(config.quantity) is not int or not 1 <= config.quantity <= 20:
            raise SafetyError("수량은 1~20이어야 합니다.")
        names.append(f"quantity_{config.quantity}")
        names.append(f"buy_cost_{config.quantity * 1600}")
    missing = set(names) - profile.templates.keys()
    if missing:
        raise SafetyError("이 동작에 필요한 이미지를 먼저 저장하세요: " + ", ".join(sorted(missing)))
    profile.templates = {name: profile.templates[name] for name in names}
    log("3초 후 선택한 동작 1회 실행. 게임을 활성화하세요. F9 중지.")
    control.delay(3)
    window = GameWindow(config.window_title)
    # User activates the game; do not steal focus from another app.
    window.check()
    log("게임 창 활성화·해상도 확인 완료")
    log("키·클릭 입력 방식: SendInput · 누름 시간 0.12초")
    capture = ScreenCapture(window)
    try:
        inputs = InputController(window, control, enabled=True)
        session = Session(config, profile, capture, inputs, control, log)
        log("실행 시작: " + definition[1])
        execute_step(session, key, config.quantity)
        log("동작 및 결과 화면 확인 완료")
        return session.frame()
    finally:
        capture.close()
