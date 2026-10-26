from automation.inventory_automation import slots, targets


def dismantle(session, amount, remaining):
    session.log(f"분해 준비 · 대상 {amount}개 / 예상 비용 {amount * 300:,} 확인 중")
    slots(session, amount)
    targets(session, remaining)
    frame = session.frame()
    session.require(frame, "dismantle_panel", f"dismantle_cost_{amount * 300}")
    if session.detector.present(frame, "complete_popup"):
        from core.state_machine import SafetyError
        raise SafetyError("분해 시작 전에 완료 팝업이 있습니다.")
    session.inputs.click(session.detector.one(frame, "dismantle_button"))
    session.log(f"분해 실행 {amount}개 · 완료 팝업 대기 중 (최대 {session.config.completion_timeout_seconds:.0f}초)")
    # Completion is observed, never inferred from an item-count timer.
    session.expect("complete_popup", session.config.completion_timeout_seconds)
    session.click("complete_confirm", "dismantle_panel")
    session.wait_absent("complete_popup")
    slots(session, 0)
    targets(session, remaining)
    session.log(f"분해 완료 확인 · {amount}개 처리 완료")
