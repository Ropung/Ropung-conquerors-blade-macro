from core.state_machine import SafetyError


def set_quantity(session, quantity):
    if type(quantity) is not int or not 1 <= quantity <= 20:
        raise SafetyError("구매 수량은 1~20이어야 합니다.")
    frame = session.frame()
    session.require(frame, "buy_popup")
    # Called once for a freshly opened purchase dialog (default quantity 1).
    session.click("quantity_field", "buy_popup")
    session.log(f"수량 입력: 기본값 1 확인 → {quantity}개 설정")
    session.inputs.quantity(quantity)
    session.control.delay(.2)
