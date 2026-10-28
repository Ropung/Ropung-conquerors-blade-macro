"""Build only reviewed, required calibration assets into the single EXE."""
from pathlib import Path
import shutil

from core.config import write_json
from core.image_detector import Detector, Profile, required_templates


def package_assets(root):
    root = Path(root)
    destination = root / "build" / "bundled_assets"
    if destination.exists():
        # Only clear this script's generated directory under the project build.
        if destination.resolve().parent != (root / "build").resolve():
            raise ValueError("잘못된 빌드 출력 경로")
        shutil.rmtree(destination)
    supported = []
    for resolution in ((2560, 1440), (1920, 1080)):
        relative = Path("calibration")
        if resolution != (2560, 1440):
            relative /= f"{resolution[0]}x{resolution[1]}"
        source = root / relative / "profile.json"
        if not source.is_file():
            continue
        profile = Profile(source, resolution)
        profile.validate(15)
        if 15 not in profile.data.get("reviewed_quantities", []):
            raise ValueError(f"배포 전 실제 화면 보정 검토 필요: {resolution}")
        names = required_templates(15)
        Detector(profile, names=names)
        target = destination / relative
        target.mkdir(parents=True, exist_ok=True)
        data = {"resolution": list(resolution), "regions": profile.regions,
                "reviewed_quantities": [15],
                "templates": {name: profile.templates[name] for name in names}}
        for spec in data["templates"].values():
            shutil.copy2(source.parent / spec["file"], target / spec["file"])
        write_json(target / "profile.json", data)
        supported.append(list(resolution))
    if not supported:
        raise ValueError("배포할 보정 프로필이 없습니다.")
    write_json(destination / "supported_resolutions.json", supported)
    return supported


if __name__ == "__main__":
    print("Embedded resolutions:", package_assets(Path(__file__).resolve().parent))
