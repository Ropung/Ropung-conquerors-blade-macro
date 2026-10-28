import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def app_root():
    if getattr(sys, "frozen", False):
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ConquerorsBladeMacro"
    return Path(__file__).resolve().parents[1]


def resource_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def profile_path(config, root):
    """Local authoring profiles take priority; releases carry their own images."""
    relative = config.calibration_profile
    local = Path(root) / relative
    return local if local.is_file() else resource_root() / relative


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
    width: int = 2560
    height: int = 1440
    set_count: int = 1
    similarity: float = 90.0

    @property
    def resolution(self):
        return (self.width, self.height)

    @property
    def calibration_profile(self):
        path = Path(self.profile)
        if self.resolution == (2560, 1440):
            return path
        return path.parent / f"{self.width}x{self.height}" / path.name

    def validate(self):
        if isinstance(self.similarity, bool) or not isinstance(self.similarity, (int, float)) or not 50 <= self.similarity <= 100:
            raise ValueError("유사도는 50~100%여야 합니다.")
        if type(self.set_count) is not int or not 1 <= self.set_count <= 10000:
            raise ValueError("세트 수는 1~10,000 정수여야 합니다.")
        if any(type(v) is not int or not 320 <= v <= 16384 for v in self.resolution):
            raise ValueError("해상도는 320~16384 범위의 정수여야 합니다.")
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
