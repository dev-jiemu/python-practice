"""수집한 줄을 레코드로 정규화하고, 매칭 종류를 판정하고, 반복을 접는다."""

import json
from datetime import timedelta

from .fields import (
    CALLER_KEYS, LEVEL_KEYS, MAX_NEST_DEPTH, MSG_KEYS, TS_KEYS, TS_SNIFF,
    VOLATILE_KEYS, caller_of, parse_embedded_json, parse_ts, pick, strip_volatile,
)


def normalize(area, host, stdout, search_field, search_value, embed=True):
    """ssh stdout(source\tfile\tline) 을 정규화된 레코드 리스트로 바꾼다."""
    records = []
    last_ts_by_stream = {}
    seq_by_stream = {}

    for out_line in stdout.splitlines():
        if not out_line.strip():
            continue

        parts = out_line.split("\t", 2)
        if len(parts) < 3:
            source, path, line = "?", "?", out_line
        else:
            source, path, line = parts

        # 같은 (호스트, 파일) 안에서의 원래 줄 순서. 정렬 키의 마지막 항목이라
        # 같은 시각에 찍힌 줄들의 인과 순서가 뒤집히지 않게 해준다.
        #
        # 전역 카운터를 쓰면 호스트별 응답이 스레드 완료 순서로 들어오는 탓에
        # 실행마다 값이 달라져서 --json 출력이 재현되지 않는다. 정렬 키에서
        # _host, _file 이 이미 앞서므로 스트림 안에서만 증가하면 충분하다.
        stream = (host, path)
        seq_by_stream[stream] = seq_by_stream.get(stream, 0) + 1

        rec = {
            "_area": area,
            "_host": host,
            "_source": source,
            "_file": path,
            "_seq": seq_by_stream[stream],
            "_raw": line,
        }

        try:
            fields = json.loads(line)
            if not isinstance(fields, dict):
                raise ValueError
            if embed:
                # body 처럼 JSON 문자열이 통째로 들어있는 필드를 풀어준다.
                fields = parse_embedded_json(fields)
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
        level_key, level = pick(fields, LEVEL_KEYS) if fields else (None, None)
        msg_key, msg = pick(fields, MSG_KEYS) if fields else (None, None)
        caller_key, _ = pick(fields, CALLER_KEYS) if fields else (None, None)
        rec["_level"] = str(level).upper() if level is not None else ""
        rec["_msg"] = str(msg) if msg is not None else ("" if fields else line)
        rec["_caller"] = caller_of(fields) if fields else ""

        # 회색 줄에서 뺄 키는 "실제로 쓴 키"만이다. 별칭 목록 전체를 빼면
        # 예컨대 msg 와 event 가 같이 있는 줄에서 event 객체가 통째로 사라진다
        # (event 는 MSG_KEYS 의 별칭이라서). 데이터가 조용히 없어지는 셈.
        # set 이 아니라 정렬된 list 로 둔다. set 은 JSON 으로 직렬화되지 않아
        # --json 출력에서 파이썬 repr 로 새는데, 그 순서가 프로세스마다 달라진다
        # (해시 시드 랜덤화). 개수가 4개 이하라 list 조회 비용은 무시할 수준.
        rec["_used_keys"] = sorted({k for k in (ts_key, level_key, msg_key, caller_key) if k})

        # --- 매칭 종류 -------------------------------------------------------
        rec["_match"] = classify_match(rec, search_field, search_value)
        rec["_sig"] = signature(rec)
        records.append(rec)

    return records


def find_value_paths(node, value, prefix="", limit=3, depth=0, partial=False):
    """value 가 들어있는 경로를 중첩 구조까지 훑어서 찾는다.

    partial=False 면 값이 통째로 같은 곳만, True 면 더 긴 문자열의 일부로
    들어있는 곳까지 찾는다.

    최상위만 보면 form_data 같은 객체 안에 든 진짜 값을 놓친다.
    (실제로 어떤 receiver 는 rid 필드에 핸들러 이름을 넣고,
     진짜 rid 는 form_data.source_file_name 배열 안에 "<rid>.mp3" 로 넣는다.)
    """
    if depth > MAX_NEST_DEPTH:
        return []

    found = []
    if isinstance(node, dict):
        for key, val in node.items():
            path = f"{prefix}.{key}" if prefix else key
            found += find_value_paths(val, value, path, limit, depth + 1, partial)
            if len(found) >= limit:
                break
    elif isinstance(node, list):
        for index, val in enumerate(node):
            found += find_value_paths(val, value, f"{prefix}[{index}]",
                                      limit, depth + 1, partial)
            if len(found) >= limit:
                break
    elif isinstance(node, (str, int, float)) and not isinstance(node, bool):
        text = str(node)
        if prefix and (text == value or (partial and value in text)):
            found.append(prefix)

    return found[:limit]


def classify_match(rec, field, value):
    """원격 grep 은 값이 어느 필드에 있든 잡는다. 여기서 정확히 구분한다.

    field          : 찾던 필드에 정확히 그 값이 들어있다 (원하는 것)
    nested:<경로>  : 중첩 구조 안에 그 값이 그대로 들어있다 — 진짜 매칭이다
    partial:<경로> : 그 경로의 값 "안에" 들어있다 ("<rid>.mp3", ffmpeg 명령줄의 경로 등)
    other:<키>     : 다른 최상위 필드에 같은 값이 있다 (예: parent_rid) — 다른 요청일 수 있다
    substring      : 값이 든 곳을 특정하지 못했다 (키 이름에 걸렸거나 이스케이프된 경우)
    raw            : JSON 이 아닌 줄 (panic/스택트레이스 등) — 항상 살린다

    --strict 는 other 와 substring 만 제외한다. rid 처럼 고유한 값이면
    partial 로 걸린 줄도 거의 같은 요청이라, 그걸 버리면 요청을 처음 받은
    시점의 원본 파라미터 로그 같은 게 통째로 날아간다.
    """
    if not rec["_json"]:
        return "raw"

    fields = rec["fields"]
    if field in fields and str(fields[field]) == value:
        return "field"

    exact = find_value_paths(fields, value)
    if exact:
        top_level = [p for p in exact if "." not in p and "[" not in p]
        if top_level:
            return f"other:{top_level[0]}"
        return f"nested:{exact[0]}"

    inside = find_value_paths(fields, value, partial=True)
    if inside:
        return f"partial:{inside[0]}"

    return "substring"


def signature(rec):
    """시각을 뺀 레코드의 지문. 이게 같으면 '내용이 똑같은 줄'이다.

    폴링 로그는 시각만 바뀌고 나머지가 동일하다 → 접힌다.
    상태가 STARTED → SUCCESS 로 바뀌면 지문이 달라진다 → 안 접힌다.
    그 전이가 정작 보고 싶은 줄이므로, 이 구분이 중요하다.
    """
    if not rec["_json"]:
        return "raw:" + rec["_raw"]
    try:
        return json.dumps(strip_volatile(rec["fields"]),
                          sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None


def collapse_runs(records):
    """같은 (영역·소스·호스트)에서 내용이 똑같은 줄이 연달아 나오면 첫 줄만 남긴다.

    남긴 줄에 _repeat(횟수)와 _repeat_until(마지막 시각)을 달아서
    "몇 번, 얼마 동안 반복됐는지"를 잃지 않는다. 폴링 로그에서는
    그 지속 시간 자체가 진단 정보다.
    """
    kept = []
    last_kept_index = {}

    for rec in records:
        group = (rec["_area"], rec["_source"], rec["_host"])
        index = last_kept_index.get(group)
        sig = rec.get("_sig")

        if index is not None and sig is not None and kept[index].get("_sig") == sig:
            head = kept[index]
            head["_repeat"] = head.get("_repeat", 1) + 1
            if rec["_ts"]:
                head["_repeat_until"] = rec["_ts"]
            continue

        kept.append(rec)
        last_kept_index[group] = len(kept) - 1

    return kept


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
