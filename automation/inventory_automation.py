from core.state_machine import SafetyError


def open_inventory(session):
    session.key("i", "inventory_open")
    session.click("dismantle_icon", "dismantle_panel")


def targets(session, expected):
    frame = session.frame()
    session.require(frame, "dismantle_panel")
    found = session.detector.find_all(frame, "inventory_target", session.profile.regions["inventory"])
    if len(found) != expected:
        raise SafetyError(f"인벤토리 대상 {expected}개 필요, 현재 {len(found)}개. 스택/가림/기존 대상 확인")
    return found


def slot_count(session):
    frame = session.frame()
    session.require(frame, "dismantle_panel")
    target_count = 0
    for index in range(15):
        region = session.profile.regions[f"slot_{index}"]
        target = len(session.detector.find_all(frame, "slot_target", region))
        empty = len(session.detector.find_all(frame, "slot_empty", region))
        if (target, empty) not in ((1, 0), (0, 1)):
            raise SafetyError(f"분해 슬롯 {index + 1}: 다른 아이템/불확실한 인식")
        target_count += target
    return target_count


def slots(session, expected):
    target_count = slot_count(session)
    if target_count != expected:
        raise SafetyError(f"분해 슬롯 대상 {expected}개 필요, 현재 {target_count}개")


def register(session, amount, remaining, initial_count=0):
    slots(session, initial_count)
    points = sorted(targets(session, remaining), key=lambda p: (p[1], p[0]))[:amount]
    if len(points) != amount:
        raise SafetyError("등록할 대상 아이콘 수가 부족합니다.")
    session.log(f"같은 아이템 {amount}개 확인 · 첫 아이템 이름·등급 확인 중")
    session.inputs.move(points[0])
    session.expect_all(("dismantle_panel", "inventory_target_name", "inventory_target_blue"), timeout=3)
    template = session.detector.images["inventory_target"]
    th, tw = template.shape[:2]
    for index, point in enumerate(points):
        # Fixed inventory cells do not shift when an item is staged. Recheck each
        # exact icon before right-click, rather than repeating full tooltip scans.
        session.inputs.move(point)
        frame = session.frame()
        session.require(frame, "dismantle_panel")
        x, y = point
        left, top = max(0, x-tw//2-2), max(0, y-th//2-2)
        region = [left, top, min(2560-left, tw+4), min(1440-top, th+4)]
        fresh = session.detector.find_all(frame, "inventory_target", region)
        if not any(abs(point[0]-p[0]) <= 2 and abs(point[1]-p[1]) <= 2 for p in fresh):
            raise SafetyError(f"등록 {initial_count + index + 1}번째: 대상 아이콘/위치가 바뀌었습니다.")
        session.inputs.click(point, button="right")
        session.log(f"등록 입력 {initial_count + index + 1}/{initial_count + amount}")
    session.control.delay(.25)
    slots(session, initial_count + amount)
    targets(session, remaining - amount)
    session.log(f"등록 최종 확인: {initial_count + amount}개 일치")
