"""로그 한 줄에서 값을 꺼내는 규칙들.

모듈마다 로거가 달라서 타임스탬프 키가 ts / time / timestamp 로 갈린다.
모듈별 파서를 만드는 대신 아래 별칭 목록에 한 줄 추가해서 흡수한다.
"""

import json
import os
import re
from datetime import datetime, timezone


TS_KEYS = ("ts", "time", "timestamp", "@timestamp", "eventTime", "datetime", "date")


LEVEL_KEYS = ("level", "lvl", "severity", "log_level", "levelname")


MSG_KEYS = ("msg", "message", "log", "event", "text")


CALLER_KEYS = ("source", "caller", "logging.googleapis.com/sourceLocation")


TS_SNIFF = re.compile(
    r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?(?:Z|[+-]\d{2}:?\d{2})?)"
)


FAR_FUTURE = datetime(9999, 1, 1, tzinfo=timezone.utc)


MAX_NEST_DEPTH = 6


EMBED_MAX_DEPTH = 3


VOLATILE_KEYS = frozenset(TS_KEYS) | frozenset(CALLER_KEYS)


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


def caller_of(fields):
    """호출 위치를 'rabbitmq.go:300' 처럼 짧게 뽑는다.

    Go slog 의 source 객체는 function 경로가 아주 길어서 그대로 찍으면
    한 줄이 화면을 다 먹는다. 정작 필요한 건 파일명과 줄 번호다.
    """
    _, raw = pick(fields, CALLER_KEYS)
    if isinstance(raw, dict):
        path = str(raw.get("file") or "")
        line_no = raw.get("line")
        base = os.path.basename(path)
        if base and line_no is not None:
            return f"{base}:{line_no}"
        return base
    if isinstance(raw, str):
        return os.path.basename(raw)  # "consumer/rabbitmq.go:300" → "rabbitmq.go:300"
    return ""


def parse_embedded_json(node, depth=0):
    """JSON 문자열이 통째로 들어있는 필드를 실제 객체로 풀어준다.

    어떤 서비스는 외부 응답을 {"body":"{\\"state\\":\\"STARTED\\",...}"} 처럼
    문자열로 통째로 박는다. 풀어놓지 않으면 안쪽 값(state 등)을 볼 수도,
    반복 판정에 쓸 수도 없다. 원본 줄은 _raw 에 그대로 남으므로 잃는 건 없다.
    """
    if depth > EMBED_MAX_DEPTH:
        return node

    if isinstance(node, dict):
        return {k: parse_embedded_json(v, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [parse_embedded_json(v, depth + 1) for v in node]
    if isinstance(node, str):
        text = node.strip()
        if len(text) > 1 and text[0] in "{[" and text[-1] in "}]":
            try:
                return parse_embedded_json(json.loads(text), depth + 1)
            except (json.JSONDecodeError, ValueError):
                return node
    return node


def strip_volatile(node, depth=0):
    if depth > MAX_NEST_DEPTH:
        return node
    if isinstance(node, dict):
        return {k: strip_volatile(v, depth + 1)
                for k, v in node.items() if k not in VOLATILE_KEYS}
    if isinstance(node, list):
        return [strip_volatile(v, depth + 1) for v in node]
    return node
