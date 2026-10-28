from dataclasses import asdict, dataclass


def set_limit(set_count):
    if type(set_count) is not int or not 1 <= set_count <= 10000:
        raise ValueError("세트 수는 1~10,000 정수여야 합니다.")
    return set_count * 15


@dataclass
class RunStats:
    purchased: int = 0
    dismantled: int = 0
    purchase_pending: int = 0
    dismantle_pending: int = 0

    def begin_purchase(self, quantity):
        self.purchase_pending = quantity

    def confirm_purchase(self):
        self.purchased += self.purchase_pending
        self.purchase_pending = 0

    def begin_dismantle(self, quantity):
        self.dismantle_pending = quantity

    def confirm_dismantle(self):
        self.dismantled += self.dismantle_pending
        self.dismantle_pending = 0

    def report(self):
        return {**asdict(self), "purchase_cost": self.purchased * 1600,
                "dismantle_cost": self.dismantled * 300,
                "total_cost": self.purchased * 1600 + self.dismantled * 300}

    def text(self):
        data = self.report()
        result = (f"확인된 구매 {self.purchased}개 · 분해 {self.dismantled}개\n"
                  f"전쟁 코인: 구매 {data['purchase_cost']:,} + 분해 {data['dismantle_cost']:,} = 합계 {data['total_cost']:,}\n"
                  "비용은 확인된 작업 수 × 단가로 계산합니다.")
        if self.purchase_pending or self.dismantle_pending:
            result += (f"\n중지 시 처리 결과 미확정: 구매 {self.purchase_pending}개 / 분해 {self.dismantle_pending}개"
                       " (위 합계에 미포함 · 게임에서 실제 잔액 확인)")
        return result


def next_quantity(quantity, limit, completed):
    return quantity if limit == 0 else max(0, min(quantity, limit - completed))
