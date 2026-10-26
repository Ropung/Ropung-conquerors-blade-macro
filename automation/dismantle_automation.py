import time

from automation.inventory_automation import slots, targets, slot_count
from core.state_machine import SafetyError


def wait_complete(session, retry_available):
    deadline = time.monotonic() + session.config.completion_timeout_seconds
    lone_since = None
    while time.monotonic() < deadline:
        frame = session.frame()
        if session.detector.present(frame, "complete_popup"):
            session.expect("complete_popup", session.config.completion_timeout_seconds)
            return True
        if retry_available:
            # A single remaining target must persist with the one-item cost;
            # a transient last item during normal processing is not enough.
            if session.detector.present(frame, "dismantle_panel") and session.detector.present(frame, "dismantle_cost_300") and slot_count(session) == 1:
                if lone_since is None:
                    lone_since = time.monotonic()
                elif time.monotonic() - lone_since >= 1.5:
                    return False
            else:
                lone_since = None
        session.control.delay(.15)
    raise SafetyError("분해 완료 팝업 대기 시간 초과")


def dismantle(session, amount, remaining):
    session.log(f"분해 준비 · 대상 {amount}개 / 예상 비용 {amount * 300:,} 확인 중")
    slots(session, amount)
    targets(session, remaining)
    frame = session.frame()
    session.require(frame, "dismantle_panel", f"dismantle_cost_{amount * 300}")
    if session.detector.present(frame, "complete_popup"):
        raise SafetyError("분해 시작 전에 완료 팝업이 있습니다.")
    for attempt in range(2):
        retry_available = attempt == 0 and amount > 1
        session.inputs.click(session.detector.one(frame, "dismantle_button"))
        session.log(f"분해 실행 · 완료 확인 중 (최대 {session.config.completion_timeout_seconds:.0f}초)")
        if wait_complete(session, retry_available):
            session.click("complete_confirm", "dismantle_panel")
            session.wait_absent("complete_popup")
        count = slot_count(session)
        if count == 0:
            break
        if count != 1 or not retry_available:
            raise SafetyError(f"분해 후 {count}개가 남았습니다. 추가 재시도 없이 중지합니다.")
        targets(session, remaining)
        frame = session.frame()
        session.require(frame, "dismantle_panel", "dismantle_cost_300")
        if session.detector.present(frame, "complete_popup"):
            raise SafetyError("완료 팝업이 열린 상태이므로 추가 분해를 중지합니다.")
        session.log("마지막 1개 남음 확인 · 분해 버튼 1회 추가 클릭")
    slots(session, 0)
    targets(session, remaining)
    session.log(f"분해 완료 확인 · {amount}개 처리 완료")
