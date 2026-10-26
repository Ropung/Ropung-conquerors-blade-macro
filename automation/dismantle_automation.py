from automation.inventory_automation import slots, targets
from core.state_machine import SafetyError


def dismantle(session, amount, remaining):
    session.log(f"분해 준비 · 대상 {amount}개 / 예상 비용 {amount * 300:,} 확인 중")
    slots(session, amount)
    targets(session, remaining)
    frame = session.frame()
    session.require(frame, "dismantle_panel", f"dismantle_cost_{amount * 300}")
    if session.detector.present(frame, "complete_popup"):
        raise SafetyError("분해 시작 전에 완료 팝업이 있습니다.")
    session.inputs.click(session.detector.one(frame, "dismantle_button"))
    session.log("분해 실행 · 확인창 대기 중")
    session.expect("complete_popup", session.config.completion_timeout_seconds)
    session.click("complete_confirm", "dismantle_panel")
    session.wait_absent("complete_popup")
    slots(session, 0)
    targets(session, remaining)
    frame = session.frame()
    session.require(frame, "dismantle_panel")
    if session.detector.present(frame, "complete_popup"):
        raise SafetyError("확인창이 남아 있어 마무리 클릭을 중지합니다.")
    session.log("확인창 닫힘 · 분해 목록 비었음 확인 · 분해 버튼 1회 마무리 클릭")
    session.inputs.click(session.detector.one(frame, "dismantle_button"))
    session.log(f"분해 완료 확인 · {amount}개 처리 완료")
