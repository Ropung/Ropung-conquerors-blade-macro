import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def app_root():
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


@dataclass
class Config:
    quantity: int = 15
    window_title: str = "컨커러스 블레이드"
    profile: str = "calibration/profile.json"
    live_input: bool = False
    timeout_seconds: float = 10
    completion_timeout_seconds: float = 90

    def validate(self):
        if type(self.quantity) is not int or not 1 <= self.quantity <= 20:
            raise ValueError("구매 수량은 1~20 정수여야 합니다.")
        if not self.window_title.strip():
            raise ValueError("게임 창 제목이 비어 있습니다.")
        if type(self.live_input) is not bool:
            raise ValueError("live_input은 boolean이어야 합니다.")
        for value in (self.timeout_seconds, self.completion_timeout_seconds):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 300:
                raise ValueError("제한 시간은 1~300초여야 합니다.")
        return self

    @classmethod
    def load(cls, root=None):
        path = (root or app_root()) / "config.json"
        config = cls(**json.loads(path.read_text(encoding="utf-8-sig"))) if path.exists() else cls()
        return config.validate()

    def save(self, root=None):
        self.validate()
        write_json((root or app_root()) / "config.json", asdict(self))
