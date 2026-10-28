import json
from pathlib import Path

from core.state_machine import SafetyError


def required_templates(quantity):
    from core.state_machine import batches
    names = {
        "shop_menu", "shop_open", "page_two", "page_two_active",
        "shop_target", "buy_button", "buy_popup",
        "inventory_target_identity",
        "quantity_field", "buy_confirm", "inventory_open", "dismantle_icon",
        "dismantle_panel", "inventory_target", "slot_target", "slot_empty",
        "dismantle_button", "complete_popup", "complete_confirm", "dismantle_cost_300",
    }
    names.update(f"dismantle_cost_{amount * 300}" for amount in batches(quantity))
    return sorted(names)


def valid_rect(rect, resolution=(2560, 1440)):
    return (isinstance(rect, list) and len(rect) == 4
            and all(type(v) is int for v in rect)
            and rect[0] >= 0 and rect[1] >= 0 and rect[2] > 0 and rect[3] > 0
            and rect[0] + rect[2] <= resolution[0] and rect[1] + rect[3] <= resolution[1])


class Profile:
    def __init__(self, path, resolution=None):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8"))
        self.resolution = self.data.get("resolution")
        if (not isinstance(self.resolution, list) or len(self.resolution) != 2
                or any(type(v) is not int or not 320 <= v <= 16384 for v in self.resolution)):
            raise SafetyError("보정 파일 해상도가 올바르지 않습니다.")
        if resolution is not None and tuple(self.resolution) != tuple(resolution):
            raise SafetyError("선택한 해상도와 보정 파일 해상도가 다릅니다. 해당 해상도에서 다시 보정하세요.")
        self.templates = self.data.get("templates", {})
        # Obsolete interaction prompt crops are no longer used or loaded.
        for obsolete in ("npc_ready", "shop_target_name", "shop_target_blue", "shop_target_identity",
                         "buy_target_name", "buy_target_blue", "inventory_target_name", "inventory_target_blue"):
            self.templates.pop(obsolete, None)
        self.regions = self.data.get("regions", {})

    def apply_similarity(self, percent):
        if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not 50 <= percent <= 100:
            raise SafetyError("유사도는 50~100%여야 합니다.")
        for spec in self.templates.values():
            spec["threshold"] = percent / 100

    def validate(self, quantity, template_names=None):
        missing = set(required_templates(quantity) if template_names is None else template_names) - self.templates.keys()
        if missing:
            raise SafetyError("템플릿 누락: " + ", ".join(sorted(missing)))
        for key in ["inventory", *[f"slot_{i}" for i in range(15)]]:
            if not valid_rect(self.regions.get(key), self.resolution):
                raise SafetyError("영역 보정 필요: " + key)
        slots = [self.regions[f"slot_{i}"] for i in range(15)]
        for i, a in enumerate(slots):
            for b in slots[i + 1:]:
                if a[0] < b[0]+b[2] and b[0] < a[0]+a[2] and a[1] < b[1]+b[3] and b[1] < a[1]+a[3]:
                    raise SafetyError("분해 슬롯 영역이 겹칩니다.")
        for name, spec in self.templates.items():
            if not valid_rect(spec.get("roi"), self.resolution):
                raise SafetyError("잘못된 템플릿 ROI: " + name)
            threshold = spec.get("threshold", 0.97)
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not .50 <= threshold <= 1:
                raise SafetyError("템플릿 임계값 범위: 0.50~1.00")
            file = (self.path.parent / spec["file"]).resolve()
            if not file.is_relative_to(self.path.parent.resolve()) or not file.is_file():
                raise SafetyError("템플릿 파일 누락/경로 오류: " + name)
        inventory = self.regions["inventory"]
        for slot in slots:
            if (inventory[0] < slot[0]+slot[2] and slot[0] < inventory[0]+inventory[2]
                    and inventory[1] < slot[1]+slot[3] and slot[1] < inventory[1]+inventory[3]):
                raise SafetyError("인벤토리와 분해 슬롯 영역이 겹칩니다.")


class Detector:
    def match_scores(self, search, template, name):
        import cv2
        import numpy as np
        if name in ("page_two", "page_two_active", "shop_menu", "quantity_plus", "quantity_minus"):
            # Page controls are translucent over the animated horse. Compare
            # only their bright arrow/digit strokes, not the moving backdrop.
            mask = (cv2.cvtColor(template, cv2.COLOR_BGR2GRAY) > 100).astype(np.uint8) * 255
            if np.count_nonzero(mask) < 5:
                raise SafetyError("메뉴 글자 또는 페이지 화살표/숫자가 보이도록 다시 캡처하세요: " + name)
            scores = cv2.matchTemplate(search, template, cv2.TM_SQDIFF_NORMED, mask=mask)
            return np.nan_to_num(scores, nan=1.0, posinf=1.0, neginf=1.0)
        return cv2.matchTemplate(search, template, cv2.TM_SQDIFF_NORMED)

    def __init__(self, profile, names=None):
        import cv2
        import numpy as np
        self.profile = profile
        self.images = {}
        for name, spec in profile.templates.items():
            if names is not None and name not in names:
                continue
            if not valid_rect(spec.get("roi"), profile.resolution):
                raise SafetyError("잘못된 템플릿 검색 영역: " + name)
            threshold = spec.get("threshold", .97)
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not .50 <= threshold <= 1:
                raise SafetyError("템플릿 임계값 범위: 0.50~1.00")
            path = profile.path.parent / spec["file"]
            if not path.resolve().is_relative_to(profile.path.parent.resolve()):
                raise SafetyError("잘못된 템플릿 경로: " + name)
            image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None or min(image.shape[:2]) < 5 or image.std() < 2:
                raise SafetyError("유효한 상세 이미지가 필요합니다: " + name)
            if name in ("slot_empty", "slot_target"):
                for key, rect in profile.regions.items():
                    if key.startswith("slot_") and valid_rect(rect, profile.resolution) and (image.shape[1] > rect[2] or image.shape[0] > rect[3]):
                        raise SafetyError(f"{name}: 이미지가 분해 한 칸보다 큽니다. 여러 칸 전체가 아닌 한 칸 내부만 다시 저장하세요.")
            self.images[name] = image

    def diagnose(self, frame, name, region=None):
        """Read-only report; score is image similarity, not a probability."""
        import cv2
        import numpy as np
        spec = self.profile.templates[name]
        roi = region or spec["roi"]
        if not valid_rect(roi, self.profile.resolution):
            raise SafetyError("잘못된 검색 영역: " + name)
        x, y, w, h = roi
        template = self.images[name]
        th, tw = template.shape[:2]
        if tw > w or th > h:
            raise SafetyError("템플릿이 검색 영역보다 큽니다: " + name)
        scores = self.match_scores(frame[y:y+h, x:x+w], template, name)
        minimum, _, location, _ = cv2.minMaxLoc(scores)
        similarity = 1 - float(minimum) if np.isfinite(minimum) else 0
        matches = self.find_all(frame, name, region)
        return {"similarity": similarity, "threshold": spec.get("threshold", .97),
                "matches": matches, "size": (tw, th), "roi": roi,
                "best": (x + location[0], y + location[1], tw, th)}

    def find_all(self, frame, name, region=None):
        import cv2
        import numpy as np
        spec = self.profile.templates[name]
        x, y, w, h = region or spec["roi"]
        template = self.images[name]
        th, tw = template.shape[:2]
        if tw > w or th > h:
            raise SafetyError("템플릿이 검색 영역보다 큽니다: " + name)
        scores = self.match_scores(frame[y:y+h, x:x+w], template, name)
        limit = 1 - spec.get("threshold", .97)
        found = []
        while True:
            minimum, _, location, _ = cv2.minMaxLoc(scores)
            if not np.isfinite(minimum) or minimum > limit:
                break
            px, py = location
            found.append((x + px + tw // 2, y + py + th // 2))
            # Suppress all overlapping matches for this physical icon.
            scores[max(0, py-th+1):py+th, max(0, px-tw+1):px+tw] = 1
            if len(found) > 100:
                raise SafetyError("너무 많은 일치 항목: " + name)
        return found

    def one(self, frame, name):
        matches = self.find_all(frame, name)
        if len(matches) != 1:
            raise SafetyError(f"{name}: 정확히 1개 인식 필요, 현재 {len(matches)}개")
        return matches[0]

    def present(self, frame, name):
        matches = self.find_all(frame, name)
        if len(matches) > 1:
            raise SafetyError("모호한 인식: " + name)
        return len(matches) == 1
