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


def slots(session, expected):
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
    if target_count != expected:
        raise SafetyError(f"분해 슬롯 대상 {expected}개 필요, 현재 {target_count}개")


def register(session, amount, remaining):
    slots(session, 0)
    for index in range(amount):
        points = targets(session, remaining - index)
        point = sorted(points, key=lambda p: (p[1], p[0]))[0]
        session.inputs.move(point)
        session.control.delay(.4)
        frame = session.frame()
        session.require(frame, "dismantle_panel", "inventory_target_name", "inventory_target_blue")
        # Reconfirm this exact icon after tooltip appears, before right clicking.
        fresh = session.detector.find_all(frame, "inventory_target", session.profile.regions["inventory"])
        if not any(abs(point[0]-p[0]) <= 2 and abs(point[1]-p[1]) <= 2 for p in fresh):
            raise SafetyError("호버 후 대상 위치가 변경됨")
        session.inputs.click(point, button="right")
        session.control.delay(.3)
        slots(session, index + 1)
        targets(session, remaining - index - 1)
