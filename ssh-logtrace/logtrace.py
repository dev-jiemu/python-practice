#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
logtrace — 여러 노드에 흩어진 JSON 로그를 특정 필드값으로 긁어와 UTC 시간순으로 병합한다.

설계 원칙
---------
1) 표준 라이브러리만 쓴다. 서드파티 패키지가 0개라서 폐쇄망에서도 그냥 돌아간다.
2) 원격 접속은 시스템 `ssh` 바이너리를 exec 한다. paramiko 를 쓰지 않으므로
   ~/.ssh/config, ssh-agent, ProxyJump, known_hosts 를 전부 OS 가 처리한다.
   → 이 스크립트는 IP 도 패스워드도 알지 못한다.
3) 원격에서는 grep -F 로 "싸고 관대한" 프리필터만 한다. jq 에 의존하지 않는다.
   정확한 필드 일치 판정은 로컬에서 json.loads() 후에 한다.
4) JSON 이 아닌 줄(panic, 스택트레이스, 기동 배너)은 버리지 않는다.
   장애 시점에 제일 보고 싶은 줄이 보통 그거다.

구성 (자세한 내용은 각 모듈의 docstring 참고)
--------------------------------------------
  ltrace/fields.py     필드 별칭, 타임스탬프 파싱, JSON 문자열 필드 풀기
  ltrace/inventory.py  인벤토리 로딩·검증
  ltrace/remote.py     원격 grep 스크립트 생성, ssh 실행, 팬아웃
  ltrace/records.py    레코드 정규화, 매칭 종류 판정, 반복 줄 접기
  ltrace/render.py     터미널 / JSONL 출력, 요약
  logtrace.py          이 파일 — CLI 파싱과 실행 흐름

사용 예
-------
  ./logtrace.py --rid abc123
  ./logtrace.py --field content_id=999 --area scheduler
  ./logtrace.py --rid abc123 --json > trace.jsonl
  ./logtrace.py --rid abc123 --dry-run        # 실제 접속 없이 원격 명령만 출력
"""

from __future__ import annotations

import argparse
import sys

from ltrace.fields import FAR_FUTURE
from ltrace.inventory import load_inventory
from ltrace.records import collapse_runs, derive_followup_values, time_window
from ltrace.remote import DEFAULT_SSH_OPTS, collect
from ltrace.render import paint, render_jsonl, render_summary, render_text


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="여러 노드의 JSON 로그를 필드값으로 긁어와 UTC 시간순으로 병합한다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-i", "--inventory", default="inventory.json")
    parser.add_argument("--rid", help="--field rid=<값> 의 축약형")
    parser.add_argument("--field", help="검색 기준. 형식: key=value")
    parser.add_argument("--where", action="append", default=[],
                        help="추가 로컬 필터 (반복 가능). 형식: key=value")
    parser.add_argument("--area", action="append", default=[],
                        help="특정 영역만 조회 (반복 가능)")
    parser.add_argument("--after", type=int, default=0,
                        help="grep 컨텍스트 줄 수 (스택트레이스용)")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--workers", type=int, default=0, help="0이면 자동")
    parser.add_argument("--strict", action="store_true",
                        help="다른 요청으로 보이는 줄(other)과 값의 위치를 "
                             "특정하지 못한 줄(substring)을 제외한다")
    parser.add_argument("--no-followup", action="store_true",
                        help="라운드2(파생키 재조회)를 건너뛴다")
    parser.add_argument("--no-collapse", action="store_true",
                        help="내용이 똑같이 반복되는 줄을 접지 않고 전부 보여준다")
    parser.add_argument("--no-embed", action="store_true",
                        help="JSON 문자열이 든 필드(body 등)를 풀지 않는다")
    parser.add_argument("--json", action="store_true", help="JSONL 로 출력")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--no-extra", action="store_true",
                        help="나머지 JSON 필드를 출력하지 않는다")
    parser.add_argument("--extra-width", type=int, default=400, metavar="N",
                        help="회색 필드 줄의 최대 길이. 0 이면 자르지 않는다 (기본 400)")
    parser.add_argument("--value-cap", type=int, default=120, metavar="N",
                        help="개별 값의 최대 길이. 0 이면 자르지 않는다 (기본 120)")
    parser.add_argument("--dry-run", action="store_true",
                        help="접속 없이 원격 명령만 출력")

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
                              workers, args.after, args.dry_run,
                              embed=not args.no_embed)

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
                                        workers, args.after, False,
                                        embed=not args.no_embed)
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
        records = [
            r for r in records
            if not (r["_match"] == "substring" or r["_match"].startswith("other:"))
        ]

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

    total_before_collapse = len(records)
    if not args.no_collapse:
        records = collapse_runs(records)
    collapsed = total_before_collapse - len(records)

    if not records:
        print(paint(f"결과 없음: {field}={value}", "yellow", color), file=sys.stderr)
        render_summary(records, errors, area_order, derived_all, window, color, sys.stderr)
        return 1

    if args.json:
        render_jsonl(records)
    else:
        render_text(records, area_order, color, show_extra=not args.no_extra,
                    extra_width=args.extra_width, value_cap=args.value_cap)

    render_summary(records, errors, area_order, derived_all, window, color, sys.stderr,
                   collapsed=collapsed)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
