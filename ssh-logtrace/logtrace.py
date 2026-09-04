#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
logtrace — 여러 노드에 흩어진 JSON 로그를 특정 필드값으로 긁어와 UTC 시간순으로 병합한다.
1단계: 일단 grep 기준으로 데이터를 묶어오고 정렬하는 스크립트까지만 진행

ex)
  ./logtrace.py --rid abc123
  ./logtrace.py --field content_id=999 --area scheduler
  ./logtrace.py --rid abc123 --json > trace.jsonl
  ./logtrace.py --rid abc123 --dry-run        # 실제 접속 없이 원격 명령만 출력
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from concurrent import futures
from datetime import timezone, datetime, timedelta

from coverage.debug import CALLS

# 필드명이 어떤게 올지 몰라서 대강 나열 - time, level, message
TS_KEYS = ("ts", "time", "timestamp", "@timestamp", "eventTime", "datetime", "date")
LEVEL_KEYS = ("level", "lvl", "severity", "log_level", "levelname")
MSG_KEYS = ("msg", "message", "log", "event", "text")

CALLER_KEYS = ("source", "caller", "logging.googleapis.com/sourceLocation")

DEFAULT_SSH_OPTS = [
    "-o", "BatchMode=yes",        # 패스워드 프롬프트로 매달리지 말고 즉시 실패
    "-o", "ConnectTimeout=10",
    "-o", "LogLevel=ERROR",
]

TS_SNIFF = re.compile(
    r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?(?:Z|[+-]\d{2}:?\d{2})?)"
)

FAR_FUTURE = datetime(9999, 1, 1, tzinfo=timezone.utc)

def load_inventory(path):
    with open(path, encoding="utf-8") as fp:
        inv = json.load(fp)

    if not isinstance(inv.get("areas"), list) or not inv["areas"]:
        raise SystemExit(f"[인벤토리 오류] {path}: 'areas' 배열이 비어 있습니다.")

    for area in inv["areas"]:
        for required in ("name", "hosts", "sources"):
            if required not in area:
                raise SystemExit(f"[인벤토리 오류] area 에 '{required}' 가 없습니다: {area!r}")

        for src in area["sources"] + (area.get("followup") or {}).get("sources", []):
            if "name" not in src or "paths" not in src:
                raise SystemExit(f"[인벤토리 오류] source 에 name/paths 가 없습니다: {src!r}")

    return inv

# 원격 명령 생성
def build_remote_script(sources, pattern, after=0):
    quoted_pattern = shlex.quote(pattern)
    ctx = f"-A {int(after)}" if after else ""
    blocks = []

    for src in sources:
        for raw_path in src["paths"]:
            blocks.append(
                f'for f in {raw_path}; do\n'
                f'  [ -r "$f" ] || continue\n'
                f'  case "$f" in\n'
                f'    *.gz) gzip -cd -- "$f" 2>/dev/null'
                f' | grep -F -a {ctx} -e {quoted_pattern} ;;\n'
                f'    *)    grep -F -a -h {ctx} -e {quoted_pattern} -- "$f" 2>/dev/null ;;\n'
                f'  esac | awk -v f="$f" -v s={shlex.quote(src["name"])} '
                f"'$0==\"--\"{{next}} {{print s \"\\t\" f \"\\t\" $0}}'\n"
                f'done'
            )

    blocks.append("exit 0")
    return "\n".join(blocks)

def run_ssh(host, script, ssh_opts, timeout):
    cmd = ["ssh", *ssh_opts, host, "bash -s"]

    try:
        proc = subprocess.run(
            cmd,
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return host, "", f"타임아웃 ({timeout}s)"
    except FileNotFoundError:
        return host, "", "ssh 바이너리를 찾을 수 없음"

    err = ""
    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or f"ssh 종료코드 {proc.returncode}"
    elif proc.stderr.strip():
        err = proc.stderr.strip()

    return host, proc.stdout, err

# 타임스태프 정규화 처리 : UTC 기준임
def parse_ts(value):
    if value is None:
        return None

    # epoch (초/밀리/마이크로/나노 자동 판별)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _from_epoch(float(value))

    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    if re.fullmatch(r"\d{9,19}(?:\.\d+)?", text):
        return _from_epoch(float(text))

    return _from_iso(text)

def _from_epoch(number):
    for divisor in (1.0, 1e3, 1e6, 1e9):
        seconds = number / divisor
        if 1e8 < seconds < 4e9:  # 1973 ~ 2096 범위면 그 단위로 본다
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
    return None


def _from_iso(text):
    text = text.replace(",", ".")

    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"

    # fromisoformat 은 소수점 이하 3 또는 6자리만 받는다. 나노초는 잘라낸다.
    frac = re.search(r"\.(\d+)", text)
    if frac and len(frac.group(1)) > 6:
        text = text[: frac.start(1) + 6] + text[frac.end(1) :]

    if len(text) > 10 and text[10] == " ":
        text = text[:10] + "T" + text[11:]

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    # 타임존 표기가 없으면 UTC 로 간주한다 (전 구간 UTC 라는 전제)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def pick(mapping, keys):
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return key, mapping[key]
    return None, None

# go slog 파일의 경우 source 링크가 너무 길어서 축약할거임
def caller_of(fields):
    _, raw = pick(fields, CALLER_KEYS)
    if isinstance(raw, dict):
        path = str(raw.get("file") or "")
        line_no = raw.get("line")
        base = os.path.basename(path)
        if base and line_no is not None:
            return f"{base}:{line_no}"
        return base

    if isinstance(raw, str):
        return os.path.basename(raw) # "consumer/rabbitmq.go:300" → "rabbitmq.go:300"

    return ""


# 레코드 정규화
_counter = 0
def _next_seq():
    global _counter
    _counter += 1
    return _counter

# stdout 데이터를 레코드 리스트로 변경함
def normalize(area, host, stdout, search_field, search_value):
    records = []
    last_ts_by_stream = {}

    for out_line in stdout.splitlines():
        if not out_line.strip():
            continue

        parts = out_line.split("\t", 2)
        if len(parts) < 3:
            source, path, line = "?", "?", out_line
        else:
            source, path, line = parts

        rec = {
            "_area": area,
            "_host": host,
            "_source": source,
            "_file": path,
            "_seq": _next_seq(),
            "_raw": line,
        }

        try:
            fields = json.loads(line)
            if not isinstance(fields, dict):
                raise ValueError
            rec["_json"] = True
        except (json.JSONDecodeError, ValueError):
            fields = {}
            rec["_json"] = False

        rec["fields"] = fields

        # --- 타임스탬프 -----------------------------------------------------
        ts_key, ts_raw = pick(fields, TS_KEYS) if fields else (None, None)
        ts = parse_ts(ts_raw)
        if ts is None:
            sniffed = TS_SNIFF.search(line)
            if sniffed:
                ts = parse_ts(sniffed.group(1))

        stream = (host, path)
        if ts is None:
            # 스택트레이스 연속 줄 등은 직전 줄의 시각을 물려받아야 순서가 안 깨진다
            ts = last_ts_by_stream.get(stream)
            rec["_ts_inherited"] = ts is not None
        else:
            last_ts_by_stream[stream] = ts
            rec["_ts_inherited"] = False

        rec["_ts"] = ts
        rec["_ts_key"] = ts_key

        # --- 레벨 / 메시지 ---------------------------------------------------
        _, level = pick(fields, LEVEL_KEYS) if fields else (None, None)
        _, msg = pick(fields, MSG_KEYS) if fields else (None, None)
        rec["_level"] = str(level).upper() if level is not None else ""
        rec["_msg"] = str(msg) if msg is not None else ("" if fields else line)
        rec["_caller"] = caller_of(fields) if fields else ""

        # --- 매칭 종류 -------------------------------------------------------
        rec["_match"] = classify_match(rec, search_field, search_value)
        records.append(rec)

    return records


def classify_match(rec, field, value):
    """원격 grep 은 값이 어느 필드에 있든 잡는다. 여기서 정확히 구분한다.

    field      : 찾던 필드에 정확히 그 값이 들어있다 (원하는 것)
    other:<k>  : 다른 필드에 같은 값이 있다 (참고용, --strict 로 제외 가능)
    substring  : JSON 이지만 어느 필드값과도 정확히 안 맞는다 (부분 문자열 우연 일치)
    raw        : JSON 이 아닌 줄 (panic/스택트레이스 등) — 항상 살린다
    """
    if not rec["_json"]:
        return "raw"

    fields = rec["fields"]
    if field in fields and str(fields[field]) == value:
        return "field"

    for key, val in fields.items():
        if isinstance(val, (str, int, float)) and str(val) == value:
            return f"other:{key}"

    return "substring"


# ---------------------------------------------------------------------------
# 수집 라운드
# ---------------------------------------------------------------------------
def collect(targets, ssh_opts, timeout, workers, after, dry_run):
    """targets: [(area_name, host, [sources], field, value), ...]"""
    records, errors = [], []

    if dry_run:
        seen = set()
        for area, host, sources, field, value in targets:
            key = (area, tuple(s["name"] for s in sources), value)
            if key in seen:
                continue
            seen.add(key)
            print(f"\n===== {area} / {[s['name'] for s in sources]} "
                  f"({field}={value}) — 예: ssh {host} 'bash -s' =====")
            print(build_remote_script(sources, value, after))
        return records, errors

    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {}
        for area, host, sources, field, value in targets:
            script = build_remote_script(sources, value, after)
            fut = pool.submit(run_ssh, host, script, ssh_opts, timeout)
            pending[fut] = (area, host, field, value)

        for fut in futures.as_completed(pending):
            area, host, field, value = pending[fut]
            _, stdout, err = fut.result()
            if err:
                # 한 대가 죽어도 그냥 진행함
                errors.append((area, host, err))
            if stdout:
                records.extend(normalize(area, host, stdout, field, value))

    return records, errors


def derive_followup_values(records, key, area_name=None):
    """라운드1 결과에서 후속 검색용 값(예: content_id)을 뽑는다.

    area_name 이 None 이면 전 영역에서 찾는다 (해당 영역에서 못 찾았을 때의 폴백).
    """
    values = set()
    for rec in records:
        if area_name is not None and rec["_area"] != area_name:
            continue
        if rec["_json"]:
            val = rec["fields"].get(key)
            if val not in (None, ""):
                values.add(str(val))
    return sorted(values)


def time_window(records, area_name, margin_seconds):
    stamps = [
        r["_ts"] for r in records
        if r["_ts"] and (area_name is None or r["_area"] == area_name)
    ]
    if not stamps:
        return None
    margin = timedelta(seconds=margin_seconds)
    return min(stamps) - margin, max(stamps) + margin


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
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


def render_text(records, area_order, color, show_extra=True):
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

        if show_extra:
            extra = extra_fields(rec)
            if extra:
                print(paint("      " + extra, "dim", color))
        if rec["_match"].startswith("other:"):
            print(paint(f"      ⚠ 검색값이 '{rec['_match'][6:]}' 필드에서 매칭됨",
                        "yellow", color))


def extra_fields(rec):
    if not rec["_json"]:
        return ""
    skip = set(TS_KEYS) | set(LEVEL_KEYS) | set(MSG_KEYS) | set(CALLER_KEYS)
    rest = {k: v for k, v in rec["fields"].items() if k not in skip}
    if not rest:
        return ""
    text = json.dumps(rest, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= 400 else text[:397] + "..."


def render_jsonl(records):
    for rec in records:
        out = dict(rec)
        out["_ts"] = rec["_ts"].isoformat() if rec["_ts"] else None
        print(json.dumps(out, ensure_ascii=False, default=str))


def render_summary(records, errors, area_order, derived, window, color, stream):
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

    weak = sum(1 for r in records if r["_match"] == "substring")
    if weak:
        emit(paint(f"  ⚠ 필드 정확일치가 아닌 줄 {weak}건 (--strict 로 제외 가능)",
                   "yellow", color))

    if errors:
        emit(paint(f"\n  실패한 호스트 {len(errors)}대", "red", color))
        for area, host, err in errors:
            emit(paint(f"    {area}/{host}: {err}", "red", color))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="여러 노드의 JSON 로그를 필드값으로 긁어와 UTC 시간순으로 병합한다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-i", "--inventory", default="inventory.json")
    parser.add_argument("--rid", help="--field rid=<값> 의 축약형")
    parser.add_argument("--field", help="검색 기준. 형식: key=value")
    parser.add_argument("--where", action="append", default=[], help="추가 로컬 필터 (반복 가능). 형식: key=value")
    parser.add_argument("--area", action="append", default=[], help="특정 영역만 조회 (반복 가능)")
    parser.add_argument("--after", type=int, default=0, help="grep 컨텍스트 줄 수 (스택트레이스용)")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--workers", type=int, default=0, help="0이면 자동")
    parser.add_argument("--strict", action="store_true", help="찾는 필드에 정확히 일치하는 줄만 남긴다")
    parser.add_argument("--no-followup", action="store_true", help="라운드2(파생키 재조회)를 건너뛴다")
    parser.add_argument("--json", action="store_true", help="JSONL 로 출력")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--no-extra", action="store_true", help="나머지 JSON 필드를 출력하지 않는다")
    parser.add_argument("--dry-run", action="store_true", help="접속 없이 원격 명령만 출력")

    args = parser.parse_args(argv)

    if args.rid:
        args.field = f"rid={args.rid}"
    if not args.field:
        parser.error("--rid 또는 --field key=value 중 하나는 필요합니다.")
    if "=" not in args.field:
        parser.error("--field 형식은 key=value 입니다.")

    return args


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    inventory = load_inventory(args.inventory)

    field, value = args.field.split("=", 1)
    ssh_opts = inventory.get("ssh_opts", DEFAULT_SSH_OPTS)
    color = not args.no_color and sys.stdout.isatty() and not args.json

    areas = inventory["areas"]
    if args.area:
        areas = [a for a in areas if a["name"] in args.area]
        if not areas:
            raise SystemExit(f"[오류] 해당 영역이 인벤토리에 없습니다: {args.area}")
    area_order = [a["name"] for a in areas]

    workers = args.workers or min(16, max(4, sum(len(a["hosts"]) for a in areas)))

    # ---- 라운드 1 ---------------------------------------------------------
    round1_targets = [
        (area["name"], host, area["sources"], field, value)
        for area in areas
        for host in area["hosts"]
    ]
    records, errors = collect(round1_targets, ssh_opts, args.timeout,
                              workers, args.after, args.dry_run)

    # ---- 라운드 2 (파생키) -------------------------------------------------
    derived_all, window = [], None
    if not args.no_followup and not args.dry_run:
        round2_targets = []
        for area in areas:
            followup = area.get("followup") or None
            if not followup:
                continue

            margin = followup.get("window_seconds", 600)
            key = followup["key"]

            derived = derive_followup_values(records, key, area["name"])
            window = time_window(records, area["name"], margin)

            if not derived:
                # 해당 영역에서 못 찾았다는 것 자체가 진단 정보다 (거기까지 도달 못 함).
                # 다만 다른 영역 로그에 같은 키가 있으면 그걸로라도 후속 조회는 해본다.
                fallback = derive_followup_values(records, key)
                if not fallback:
                    print(paint(
                        f"[알림] '{key}' 를 어느 영역에서도 찾지 못했습니다."
                        f" → followup.key 이름이 실제 로그와 다를 수 있습니다.",
                        "yellow", color), file=sys.stderr)
                    continue
                print(paint(
                    f"[알림] {area['name']} 라운드1 에는 '{key}' 가 없어 다른 영역에서 가져왔습니다"
                    f" ({', '.join(fallback)})."
                    f" → 이 rid 가 {area['name']} 까지 도달하지 못했을 수 있습니다.",
                    "yellow", color), file=sys.stderr)
                derived = fallback
                window = time_window(records, None, margin)

            derived_all.extend(derived)

            for host in area["hosts"]:
                for derived_value in derived:
                    round2_targets.append(
                        (area["name"], host, followup["sources"],
                         key, derived_value)
                    )

        if round2_targets:
            more, more_errors = collect(round2_targets, ssh_opts, args.timeout,
                                        workers, args.after, False)
            errors.extend(more_errors)

            # content_id 는 그 콘텐츠의 과거 요청 전부에 찍혀 있다.
            # 라운드1 시간창으로 좁히지 않으면 무관한 건들이 타임라인을 덮는다.
            if window:
                low, high = window
                kept = [r for r in more if r["_ts"] is None or low <= r["_ts"] <= high]
                dropped = len(more) - len(kept)
                if dropped:
                    print(paint(f"[알림] 시간창 밖 라운드2 결과 {dropped}건 제외",
                                "dim", color), file=sys.stderr)
                more = kept
            records.extend(more)

    if args.dry_run:
        return 0

    # ---- 로컬 필터 --------------------------------------------------------
    if args.strict:
        records = [r for r in records if r["_match"] in ("field", "raw")]

    for clause in args.where:
        if "=" not in clause:
            raise SystemExit(f"[오류] --where 형식은 key=value 입니다: {clause}")
        where_key, where_value = clause.split("=", 1)
        records = [
            r for r in records
            if not r["_json"] or str(r["fields"].get(where_key)) == where_value
        ]

    # ---- 정렬 -------------------------------------------------------------
    # 전 구간 UTC 이므로 시각만 맞추면 그대로 정렬된다.
    # 같은 시각이면 원래 스트림 순서(_seq)를 유지해서 인과 순서가 안 뒤집히게 한다.
    records.sort(key=lambda r: (r["_ts"] or FAR_FUTURE, r["_host"], r["_file"], r["_seq"]))

    if not records:
        print(paint(f"결과 없음: {field}={value}", "yellow", color), file=sys.stderr)
        render_summary(records, errors, area_order, derived_all, window, color, sys.stderr)
        return 1

    if args.json:
        render_jsonl(records)
    else:
        render_text(records, area_order, color, show_extra=not args.no_extra)

    render_summary(records, errors, area_order, derived_all, window, color, sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)