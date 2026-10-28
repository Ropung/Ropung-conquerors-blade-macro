from automation.npc_interaction import open_shop
from automation.quantity_control import set_quantity


def purchase(session, quantity):
    open_shop(session)
    # Hovering the item changes the whole row's background. Verify its identity
    # and the row-specific purchase button together, then open that button.
    frame = session.expect("shop_target", timeout=3)
    session.require(frame, "shop_target", "buy_button")
    session.inputs.click(session.detector.one(frame, "buy_button"))
    session.expect("buy_popup")
    set_quantity(session, quantity)
    # The item was verified in the shop row before opening this fresh dialog.
    # Confirm directly after entry; quantity/cost screenshots are not required.
    frame = session.frame()
    session.control.stats.begin_purchase(quantity)
    session.inputs.click(session.detector.one(frame, "buy_confirm"))
    session.wait_absent("buy_popup")
    session.expect("shop_open")
    session.control.stats.confirm_purchase()
    session.close_ui("shop_open")
