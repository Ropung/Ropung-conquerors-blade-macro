from core.state_machine import SafetyError


def set_quantity(session, quantity):
    if type(quantity) is not int or not 1 <= quantity <= 20:
        raise SafetyError("구매 수량은 1~20이어야 합니다.")

    def press(name, count):
        for _ in range(count):
            frame = session.frame()
            session.require(frame, "buy_popup")
            point = session.detector.one(frame, name)
            session.inputs.move(point, fast=True)
            session.inputs.click(point, positioned=True)
            session.control.delay(.04)

    session.require(session.frame(), "buy_popup")
    if not session.detector.present(session.frame(), "buy_cost_1600"):
        session.log("수량 − 버튼으로 최소 1개로 초기화")
        press("quantity_minus", 19)
    session.expect("buy_cost_1600", timeout=2)
    session.log(f"수량 + 버튼으로 {quantity}개 설정 · 키보드 선택 사용 안 함")
    press("quantity_plus", quantity - 1)
    session.expect_all((f"quantity_{quantity}", f"buy_cost_{quantity * 1600}"), timeout=2)
