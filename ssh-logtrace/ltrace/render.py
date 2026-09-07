"""터미널 / JSONL 출력과 요약."""

import json

from .fields import CALLER_KEYS, LEVEL_KEYS, MAX_NEST_DEPTH, MSG_KEYS, TS_KEYS


COLORS = {
    "reset": "\033[0m", "dim": "\033[2m", "bold": "\033[1m",
    "red": "\033[31m", "yellow": "\033[33m", "green": "\033[32m",
    "blue": "\033[34m", "magenta": "\033[35m", "cyan": "\033[36m",
}


AREA_COLORS = ["cyan", "magenta", "green", "blue", "yellow"]


LEVEL_COLORS = {"ERROR": "red", "FATAL": "red", "PANIC": "red",
                "WARN": "yellow", "WARNING": "yellow", "DEBUG": "dim"}


def paint(text, color, enabled):
    if not enabled or not color:
        return text
    return f"{COLORS[color]}{text}{COLORS['reset']}"


def fmt_ts(rec):
    if rec["_ts"] is None:
        return "--:--:--.---"
    stamp = rec["_ts"].strftime("%H:%M:%S.%f")[:-3]
    return f"~{stamp}" if rec.get("_ts_inherited") else f" {stamp}"


def fmt_duration(seconds):
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def match_note(match):
    """정확일치가 아닌 줄에 왜 걸렸는지 한 줄로 알려준다."""
    if match.startswith("nested:"):
        return f"↳ 검색값이 중첩 구조 {match[7:]} 안에 있음"
    if match.startswith("partial:"):
        return f"↳ 검색값이 {match[8:]} 의 값 안에 포함됨"
    if match.startswith("other:"):
        return f"⚠ 검색값이 '{match[6:]}' 필드에서 매칭됨 (다른 요청일 수 있음)"
    if match == "substring":
        return "⚠ 값이 든 위치를 특정하지 못함"
    return ""


def shorten_values(node, cap, depth=0):
    """개별 값이 너무 길면 값 단위로 줄인다.

    줄 전체를 뒤에서 자르면 sort_keys 때문에 알파벳 뒤쪽 키(rid, task_id ...)가
    통째로 사라진다. 값마다 줄이면 어떤 키가 있었는지는 남는다.
    """
    if cap <= 0 or depth > MAX_NEST_DEPTH:
        return node
    if isinstance(node, dict):
        return {k: shorten_values(v, cap, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [shorten_values(v, cap, depth + 1) for v in node]
    if isinstance(node, str) and len(node) > cap:
        return node[: cap - 1] + "…"
    return node


def extra_fields(rec, width=400, value_cap=120):
    if not rec["_json"]:
        return ""
    skip = rec.get("_used_keys") or ()
    rest = {k: v for k, v in rec["fields"].items() if k not in skip}
    if not rest:
        return ""

    text = json.dumps(shorten_values(rest, value_cap), ensure_ascii=False,
                      sort_keys=True, default=str)
    if width <= 0 or len(text) <= width:
        return text
    return text[: width - 3] + "..."


def render_text(records, area_order, color, show_extra=True,
                extra_width=400, value_cap=120):
    area_color = {name: AREA_COLORS[i % len(AREA_COLORS)]
                  for i, name in enumerate(area_order)}
    label_width = max((len(f"{r['_area']}/{r['_source']}") for r in records), default=12)
    host_width = max((len(r["_host"]) for r in records), default=8)

    prev_day = None
    for rec in records:
        if rec["_ts"] and rec["_ts"].date() != prev_day:
            prev_day = rec["_ts"].date()
            print(paint(f"\n──── {prev_day} (UTC) ────", "dim", color))

        label = f"{rec['_area']}/{rec['_source']}".ljust(label_width)
        level = (rec["_level"] or "")[:5].ljust(5)

        body = rec["_msg"] or rec["_raw"]
        if rec.get("_caller"):
            body += "  " + paint(f"({rec['_caller']})", "dim", color)

        line = "  ".join([
            paint(fmt_ts(rec), "dim", color),
            paint(label, area_color.get(rec["_area"]), color),
            rec["_host"].ljust(host_width),
            paint(level, LEVEL_COLORS.get(rec["_level"]), color),
            body,
        ])
        print(line)

        # 값이 중첩 구조나 더 긴 값 안에 숨어 있는 줄은 --no-extra 여도 필드를 보여준다.
        # 그런 줄은 메인 한 줄만 봐서는 왜 걸렸는지도, 뭐가 들었는지도 알 수 없다.
        buried = rec["_match"].startswith(("nested:", "partial:"))
        if show_extra or buried:
            extra = extra_fields(rec, extra_width, value_cap)
            if extra:
                print(paint("      " + extra, "dim", color))
        repeat = rec.get("_repeat", 1)
        if repeat > 1:
            span = ""
            if rec["_ts"] and rec.get("_repeat_until"):
                seconds = (rec["_repeat_until"] - rec["_ts"]).total_seconds()
                span = (f" — {rec['_ts'].strftime('%H:%M:%S')}"
                        f" → {rec['_repeat_until'].strftime('%H:%M:%S')}"
                        f" ({fmt_duration(seconds)})")
            print(paint(f"      ⟲ 같은 내용 {repeat}회 반복{span}", "cyan", color))

        note = match_note(rec["_match"])
        if note:
            print(paint("      " + note, "yellow", color))


def render_jsonl(records):
    for rec in records:
        out = dict(rec)
        out["_ts"] = rec["_ts"].isoformat() if rec["_ts"] else None
        print(json.dumps(out, ensure_ascii=False, default=str))


def render_summary(records, errors, area_order, derived, window, color, stream,
                   collapsed=0):
    def emit(text=""):
        print(text, file=stream)

    emit(paint("\n===== 요약 =====", "bold", color))

    counts = {}
    for rec in records:
        counts[(rec["_area"], rec["_source"], rec["_host"])] = \
            counts.get((rec["_area"], rec["_source"], rec["_host"]), 0) + 1

    for area in area_order:
        rows = {k: v for k, v in counts.items() if k[0] == area}
        if not rows:
            emit(paint(f"  {area:<12} 결과 없음", "yellow", color))
            continue
        detail = ", ".join(f"{host}:{src}={n}" for (_, src, host), n in sorted(rows.items()))
        emit(f"  {area:<12} {sum(rows.values()):>4}건  ({detail})")

    # 구간 갭 — 이 도구의 진짜 목적
    spans = []
    for area in area_order:
        stamps = [r["_ts"] for r in records if r["_area"] == area and r["_ts"]]
        if stamps:
            spans.append((area, min(stamps), max(stamps)))

    if len(spans) > 1:
        emit(paint("\n  구간 (UTC)", "bold", color))
        for index, (area, first, last) in enumerate(spans):
            duration = (last - first).total_seconds()
            emit(f"    {area:<12} {first.strftime('%H:%M:%S.%f')[:-3]}"
                 f" → {last.strftime('%H:%M:%S.%f')[:-3]}  ({duration:.3f}s)")
            if index + 1 < len(spans):
                gap = (spans[index + 1][1] - last).total_seconds()
                marker = "red" if gap > 5 else "dim"
                emit(paint(f"      ↓ 갭 {gap:+.3f}s", marker, color))

    if derived:
        emit(f"\n  라운드2 파생키: {', '.join(derived)}")
    if window:
        emit(f"  라운드2 시간창: {window[0].isoformat()} ~ {window[1].isoformat()}")

    no_ts = sum(1 for r in records if r["_ts"] is None)
    if no_ts:
        emit(paint(f"  ⚠ 타임스탬프를 못 읽은 줄 {no_ts}건 (맨 뒤로 정렬됨)"
                   f" — TS_KEYS 에 키 추가 필요할 수 있음", "yellow", color))

    def count(pred):
        return sum(1 for r in records if pred(r["_match"]))

    if collapsed:
        emit(f"\n  반복돼서 접힌 줄 {collapsed}건 (--no-collapse 로 전부 보기)")

    soft = []
    nested = count(lambda m: m.startswith("nested:"))
    partial = count(lambda m: m.startswith("partial:"))
    if nested:
        soft.append(f"중첩 구조 안 {nested}건")
    if partial:
        soft.append(f"더 긴 값 안에 포함 {partial}건")
    if soft:
        emit(f"\n  필드 정확일치는 아니지만 같은 요청으로 보이는 줄: {', '.join(soft)}")

    other = count(lambda m: m.startswith("other:"))
    weak = count(lambda m: m == "substring")
    if other or weak:
        parts = []
        if other:
            parts.append(f"다른 필드 매칭 {other}건")
        if weak:
            parts.append(f"위치 특정 실패 {weak}건")
        emit(paint(f"  ⚠ {', '.join(parts)} (--strict 로 제외 가능)", "yellow", color))

    if errors:
        emit(paint(f"\n  실패한 호스트 {len(errors)}대", "red", color))
        for area, host, err in errors:
            emit(paint(f"    {area}/{host}: {err}", "red", color))
