import time

from automation.inventory_automation import slots, targets, slot_count
from core.state_machine import SafetyError


def wait_for_completion(session, remaining):
    deadline = time.monotonic() + session.config.completion_timeout_seconds
    lone_since = None
    retried = False
    while time.monotonic() < deadline:
        frame = session.frame()
        if session.detector.present(frame, "complete_popup"):
            session.expect("complete_popup", session.config.completion_timeout_seconds)
            return
        lone = (not retried
                and session.detector.present(frame, "dismantle_panel")
                and session.detector.present(frame, "dismantle_cost_300")
                and slot_count(session) == 1)
        if lone:
            if lone_since is None:
                lone_since = time.monotonic()
            elif time.monotonic() - lone_since >= 1.5:
                targets(session, remaining)
                slots(session, 1)
                frame = session.frame()
                session.require(frame, "dismantle_panel", "dismantle_cost_300")
                if session.detector.present(frame, "complete_popup"):
                    continue
                session.log("확인창 없이 마지막 1개가 남음 · 분해 버튼 1회 재클릭")
                session.inputs.click(session.detector.one(frame, "dismantle_button"))
                retried = True
        else:
            lone_since = None
        session.control.delay(.15)
    raise SafetyError("분해 완료 확인 시간 초과 (마지막 1개 재시도는 최대 1회)")


def dismantle(session, amount, remaining):
    session.log(f"분해 준비 · 대상 {amount}개 / 예상 비용 {amount * 300:,} 확인 중")
    slots(session, amount)
    targets(session, remaining)
    frame = session.frame()
    session.require(frame, "dismantle_panel", f"dismantle_cost_{amount * 300}")
    if session.detector.present(frame, "complete_popup"):
        raise SafetyError("분해 시작 전에 완료 팝업이 있습니다.")
    session.control.stats.begin_dismantle(amount)
    session.inputs.click(session.detector.one(frame, "dismantle_button"))
    session.log("분해 실행 · 확인창 대기 중")
    wait_for_completion(session, remaining)
    session.click("complete_confirm", "dismantle_panel")
    session.wait_absent("complete_popup")
    left = slot_count(session)
    if left == 1:
        targets(session, remaining)
        slots(session, 1)
        frame = session.frame()
        session.require(frame, "dismantle_panel", "dismantle_cost_300")
        session.log("확인 후 마지막 1개 남음 · 분해 재실행 → 마지막 확인")
        session.inputs.click(session.detector.one(frame, "dismantle_button"))
        # The remaining item is already the retry: do not retry it again.
        session.expect("complete_popup", session.config.completion_timeout_seconds)
        session.click("complete_confirm", "dismantle_panel")
        session.wait_absent("complete_popup")
    slots(session, 0)
    session.control.stats.confirm_dismantle()
    targets(session, remaining)
    session.log(f"분해 완료 확인 · {amount}개 처리 완료")
