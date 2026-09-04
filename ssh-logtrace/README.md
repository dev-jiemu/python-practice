# logtrace

여러 노드에 흩어진 JSON 로그를 특정 필드값(rid 등)으로 긁어와 UTC 시간순으로 병합한다.

- **의존성 0개** — Python 3.9+ 표준 라이브러리만 사용
- **자격증명을 다루지 않음** — 시스템 `ssh` 를 그대로 exec 하므로 `~/.ssh/config`,
  ssh-agent, ProxyJump, known_hosts 를 OS 가 처리하도록 함


## 준비하기
1. `~/.ssh/config` 에 서버 정보 등록해두기
```
Host dev-01
    HostName 0.0.0.0
    User jiemu
```

2. 키 인증 처리하기
```
ssh-keygen -t ed25519 -f ~/.ssh/id_logtrace -C logtrace
ssh-copy-id -i ~/.ssh/id_logtrace.pub dev-01   # 노드마다 다 넣어야됨
```

3. 인벤토리 만들기
```
cp inventory.example.json inventory.json
```

## 사용하기
```shell
./logtrace.py --rid abc123                    # 기본 (라운드1 + 라운드2)
./logtrace.py --rid abc123 --dry-run          # 접속 없이 원격 명령만 확인
./logtrace.py --rid abc123 --strict           # 필드 정확일치만
./logtrace.py --rid abc123 --after 20         # 스택트레이스 뒤 20줄까지
./logtrace.py --rid abc123 --area scheduler   # 특정 영역만
./logtrace.py --rid abc123 --json > t.jsonl   # 나중에 시각화용
./logtrace.py --field content_id=555          # 임의 필드로 검색
```

**왜 라운드2에 시간창을 거는가** — content_id 는 그 콘텐츠의 과거 요청 전부에 찍혀 있다.
한 달치 로그에서 그냥 grep 하면 무관한 건들이 타임라인을 덮는다.

**왜 원격에서 정확히 필터하지 않는가** — `grep -F '"rid":"abc"'` 는 직렬화 형태
(콜론 뒤 공백, 키 순서, 숫자/문자열)에 의존해서 모듈 언어가 다르면 조용히 안 걸린다.
`jq` 는 노드에 있다는 보장이 없다. 그래서 원격은 값으로 관대하게 긁고, 정확한 필드
일치 판정은 로컬에서 `json.loads()` 후에 한다. 대신 다른 필드에서 매칭된 줄은
`⚠ 검색값이 'parent_rid' 필드에서 매칭됨` 으로 표시된다.

## 실제 환경에 맞추기

로그 필드 이름이 다르면 `logtrace.py` 상단 세 줄만 고치면 된다. 모듈별 파서를 만들 필요 없다.

```python
TS_KEYS    = ("ts", "time", "timestamp", "@timestamp", ...)
LEVEL_KEYS = ("level", "lvl", "severity", ...)
MSG_KEYS   = ("msg", "message", "log", "event", ...)
```

타임스탬프는 ISO8601(`Z`/오프셋/공백 구분), epoch 초·밀리·마이크로·나노를 자동 판별한다.
`⚠ 타임스탬프를 못 읽은 줄` 경고가 뜨면 `TS_KEYS` 에 키를 추가하면 된다.