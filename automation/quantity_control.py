from core.state_machine import SafetyError


def set_quantity(session, quantity):
    if type(quantity) is not int or not 1 <= quantity <= 20:
        raise SafetyError("구매 수량은 1~20이어야 합니다.")
    frame = session.frame()
    session.require(frame, "buy_popup")
    names = (f"quantity_{quantity}", f"buy_cost_{quantity * 1600}")
    if all(session.detector.present(frame, name) for name in names):
        return
    # Never append to an unknown or already-edited number.
    session.require(frame, "buy_cost_1600")
    session.click("quantity_field", "buy_popup")
    session.log(f"수량 입력: 기본값 1 확인 → {quantity}개 설정")
    session.inputs.quantity(quantity)
    session.control.delay(.2)
    session.expect_all(names, timeout=2)
