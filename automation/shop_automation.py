from automation.npc_interaction import open_shop


def purchase(session, quantity):
    open_shop(session)
    session.hover_target("shop_target")
    session.click("shop_target", "buy_button")
    session.click("buy_button", "buy_popup")
    session.click("quantity_field", "buy_popup")
    session.inputs.quantity(quantity)
    session.control.delay(.25)
    # All observations are repeated immediately before spending coins.
    frame = session.frame()
    session.require(frame, "buy_popup", "buy_target_name", "buy_target_blue",
                    f"quantity_{quantity}", f"buy_cost_{quantity * 1600}")
    session.control.stats.begin_purchase(quantity)
    session.inputs.click(session.detector.one(frame, "buy_confirm"))
    session.wait_absent("buy_popup")
    session.expect("shop_open")
    session.control.stats.confirm_purchase()
    session.close_ui("shop_open")
