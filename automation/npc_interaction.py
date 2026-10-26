def open_shop(session):
    session.key("f", "shop_menu")
    session.click("shop_menu", "shop_open")
    session.click("page_two", "page_two_active")
