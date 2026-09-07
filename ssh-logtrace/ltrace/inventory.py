"""인벤토리(조회 대상 정의) 로딩과 검증."""

import json


def load_inventory(path):
    with open(path, encoding="utf-8") as fp:
        inv = json.load(fp)

    if not isinstance(inv.get("areas"), list) or not inv["areas"]:
        raise SystemExit(f"[인벤토리 오류] {path}: 'areas' 배열이 비어 있습니다.")

    for area in inv["areas"]:
        for required in ("name", "hosts", "sources"):
            if required not in area:
                raise SystemExit(
                    f"[인벤토리 오류] area 에 '{required}' 가 없습니다: {area!r}"
                )
        for src in area["sources"] + (area.get("followup") or {}).get("sources", []):
            if "name" not in src or "paths" not in src:
                raise SystemExit(
                    f"[인벤토리 오류] source 에 name/paths 가 없습니다: {src!r}"
                )
    return inv
