# logtrace

여러 노드에 흩어진 JSON 로그를 특정 필드값(rid 등)으로 긁어와 UTC 시간순으로 병합한다.

- **의존성 0개** — Python 3.9+ 표준 라이브러리만 쓴다. 폐쇄망에서 PyPI 없이 그냥 돈다.
- **자격증명을 다루지 않는다** — 시스템 `ssh` 를 그대로 exec 하므로 `~/.ssh/config`,
  ssh-agent, ProxyJump, known_hosts 를 OS 가 처리한다. IP도 패스워드도 코드에 없다.

## 구성

```
logtrace.py          CLI 파싱과 실행 흐름
ltrace/
  fields.py          필드 별칭, 타임스탬프 파싱, JSON 문자열 필드 풀기
  inventory.py       인벤토리 로딩·검증
  remote.py          원격 grep 스크립트 생성, ssh 실행, 팬아웃
  records.py         레코드 정규화, 매칭 종류 판정, 반복 줄 접기
  render.py          터미널 / JSONL 출력, 요약
```

읽기 시작할 곳은 `logtrace.py` 의 `main()` 이다. 라운드1 → 라운드2 → 필터 →
정렬 → 출력 흐름이 한 화면에 들어온다.

사내 서버로 옮길 때 파일 하나로 묶고 싶으면 표준 라이브러리의 zipapp 을 쓴다:

```sh
python3 -m zipapp ltrace -o logtrace.pyz
```

## 준비

순서가 중요하다. config → 키 생성 → 배포 순으로 해야 한 번에 끝난다.

**1. `~/.ssh/config` 에 별칭 등록** (IP는 여기에만 산다)

```
Host req-01
  HostName 192.0.2.11
  User myuser
  IdentityFile ~/.ssh/id_logtrace
```

10대를 손으로 쓰기 귀찮으면 생성한다:

```sh
cat > /tmp/nodes.txt <<'EOF'
req-01 192.0.2.11
req-02 192.0.2.12
sch-01 192.0.2.21
EOF

while read -r alias ip; do
  printf 'Host %s\n  HostName %s\n  User myuser\n  IdentityFile ~/.ssh/id_logtrace\n\n' \
    "$alias" "$ip"
done < /tmp/nodes.txt >> ~/.ssh/config
```

> `BatchMode yes` 를 **config 에 넣지 말 것.** 넣으면 다음 단계의 `ssh-copy-id` 가
> 패스워드를 물어보지 못해서 실패한다. logtrace 는 그 옵션을 실행 시 명령줄로 넘긴다.

**2. 키 생성** — 노트북에서 한 번만

```sh
ssh-keygen -t ed25519 -f ~/.ssh/id_logtrace -C logtrace
ssh-add --apple-use-keychain ~/.ssh/id_logtrace   # macOS: 패스프레이즈 한 번만 입력
```

패스프레이즈는 설정하는 걸 권한다. 이 키 하나로 서버 10대에 들어갈 수 있다.

**3. 공개키 배포** — 반드시 **별칭으로** 한다

```sh
awk '{print $1}' /tmp/nodes.txt | while read -r alias; do
  echo "=== $alias ==="
  ssh-copy-id -i ~/.ssh/id_logtrace.pub "$alias"
done
```

별칭으로 하는 이유가 두 가지다.

- `ssh-copy-id` 는 내부적으로 `ssh` 를 쓰므로 **config 가 제대로 써졌는지 그 자리에서 검증**된다.
- 처음 접속하는 서버는 host key 확인(`yes`)을 묻는다. 여기서 미리 대화형으로 넘겨두면
  `known_hosts` 에 등록된다. **이걸 안 해두면 `BatchMode=yes` 로 도는 logtrace 가
  `Host key verification failed` 로 실패한다.**

노드마다 `yes` 한 번, 패스워드 한 번. 그게 마지막이다.

`ssh-copy-id: command not found` 면 수동으로 해도 같다:

```sh
cat ~/.ssh/id_logtrace.pub | ssh req-01 \
  'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
```

**4. 전체 확인**

```sh
awk '{print $1}' /tmp/nodes.txt | while read -r alias; do
  printf '%-8s ' "$alias"
  ssh -o BatchMode=yes -o ConnectTimeout=5 "$alias" 'echo ok' 2>&1 | head -1
done
```

전부 `ok` 면 준비 끝. 끝나면 `/tmp/nodes.txt` 는 지운다.

키 인증이 서버 정책으로 막혀 있다면 차선책으로 연결 재사용을 쓴다 (근본 해결은 아니지만
반복 조회에서 패스워드를 매번 안 묻는다):

```
Host req-* sch-* rcv-*
  ControlMaster auto
  ControlPath ~/.ssh/cm-%r@%h:%p
  ControlPersist 10m
```

**5. 인벤토리 작성**

```sh
cp inventory.example.json inventory.json
```

`hosts` 는 위에서 만든 ssh 별칭, `paths` 는 원격 셸이 확장하는 glob 이다.
로테이션된 `.gz` 도 잡히도록 `*` 를 넉넉히 준다.

## 사용

```sh
./logtrace.py --rid abc123                    # 기본 (라운드1 + 라운드2)
./logtrace.py --rid abc123 --dry-run          # 접속 없이 원격 명령만 확인
./logtrace.py --rid abc123 --strict           # 필드 정확일치만
./logtrace.py --rid abc123 --after 20         # 스택트레이스 뒤 20줄까지
./logtrace.py --rid abc123 --area scheduler   # 특정 영역만
./logtrace.py --rid abc123 --json > t.jsonl   # 나중에 시각화용
./logtrace.py --field content_id=555          # 임의 필드로 검색
```

처음 돌릴 땐 `--dry-run` 으로 원격 명령을 눈으로 확인하고 시작하는 걸 권한다.

## 동작

```
Round 1 (전 호스트 병렬)   requester×4, receiver×4 : grep rid
                          scheduler×2            : grep rid → debug.log 에서 content_id 추출
Round 2 (scheduler×2)     grep content_id → scheduler.log, monitor.log
                          + 라운드1 시간창 ±10분으로 필터
```

**왜 라운드2에 시간창을 거는가** — content_id 는 그 콘텐츠의 과거 요청 전부에 찍혀 있다.
한 달치 로그에서 그냥 grep 하면 무관한 건들이 타임라인을 덮는다.

**왜 원격에서 정확히 필터하지 않는가** — `grep -F '"rid":"abc"'` 는 직렬화 형태
(콜론 뒤 공백, 키 순서, 숫자/문자열)에 의존해서 모듈 언어가 다르면 조용히 안 걸린다.
`jq` 는 노드에 있다는 보장이 없다. 그래서 원격은 값으로 관대하게 긁고, 정확한 필드
일치 판정은 로컬에서 `json.loads()` 후에 한다.

로컬 판정은 레코드를 중첩 구조까지 훑어서 값이 **어디서** 걸렸는지 분류한다:

| 분류 | 뜻 | `--strict` |
|---|---|---|
| `field` | 찾던 필드에 정확히 그 값 | 남음 |
| `nested:<경로>` | 중첩 구조 안에 값이 그대로 (`form_data.source_file_name[0]`) | 남음 |
| `partial:<경로>` | 그 경로의 값 "안에" 포함 (`"<rid>.mp3"`, ffmpeg 명령줄의 경로) | 남음 |
| `other:<키>` | 다른 최상위 필드에 같은 값 (`parent_rid`) — 다른 요청일 수 있음 | 제외 |
| `substring` | 값이 든 위치를 특정 못 함 | 제외 |
| `raw` | JSON 이 아닌 줄 (panic 등) | 남음 |

정확일치가 아닌 줄은 화면에 왜 걸렸는지 한 줄로 표시된다:

```
 07:43:00.244  receiver/app  node-02  DEBUG  parameters  (handler.go:501)
      ↳ 검색값이 form_data.source_file_name[0] 의 값 안에 포함됨
```

**`--strict` 를 기본으로 쓰지 말 것.** receiver 모듈은 `rid` 필드에 핸들러 이름
(`"HandleSubtitle"`)을 넣고 진짜 rid 는 `form_data` 안에 넣는데, 그게 요청을 처음 받은
시점의 원본 파라미터 로그다. 정확일치만 남기면 그 줄이 통째로 사라진다.
rid 처럼 고유한 값으로 찾을 때는 걸린 줄이 거의 다 같은 요청이라 걸러낼 게 별로 없다.

## 반복되는 줄 접기

폴링 로그는 같은 내용이 수십 번 반복돼서 타임라인을 덮는다. 기본으로 접는다:

```
 12:37:43.012  scheduler/scheduler  node-08  DEBUG  worker checking task  (scheduler.go:802)
      ⟲ 같은 내용 9회 반복 — 12:37:43 → 12:37:58 (15s)
```

한 줄만 남기는 게 아니라 **횟수와 지속 시간**을 같이 남긴다. 폴링에서는 그 지속
시간 자체가 진단 정보이기 때문이다 ("STARTED 로 17분 묶여 있었다").

판정 기준은 **시각을 뺀 레코드 전체의 지문**이다. `msg` 만 보고 접으면 상태
전이(`STARTED` → `SUCCESS`)까지 뭉개지는데, 그게 정작 제일 보고 싶은 줄이다.
`TS_KEYS` 를 재귀적으로 제거하므로 `body` 안의 `timestamp` 같은 것도 자동으로 무시된다.

접기는 같은 (영역·소스·호스트) 안에서 **연달아** 나온 줄에만 적용된다. 중간에
다른 이벤트가 끼면 거기서 끊기므로 "폴링하다가 뭔가 일어나고 다시 폴링" 이
한 덩어리로 뭉개지지 않는다.

`--no-collapse` 로 전부 볼 수 있다.

### JSON 문자열이 든 필드 풀기

scheduler 모듈은 외부 응답을 `{"body":"{\"state\":\"STARTED\",...}"}` 처럼
문자열로 통째로 박는다. 그대로 두면 안쪽 `state` 를 볼 수도, 반복 판정에 쓸 수도
없어서 자동으로 풀어준다 (`--no-embed` 로 끔). 원본 줄은 `_raw` 에 그대로 남는다.

이 덕분에 `body` 안에 든 rid 도 찾아내서 위치를 알려준다:

```
      ↳ 검색값이 body.info.storage_key 의 값 안에 포함됨
```

## 실제 환경에 맞추기

로그 필드 이름이 다르면 `ltrace/fields.py` 상단의 별칭 목록만 고치면 된다.
모듈별 파서를 만들 필요 없다.

```python
TS_KEYS     = ("ts", "time", "timestamp", "@timestamp", ...)
LEVEL_KEYS  = ("level", "lvl", "severity", ...)
MSG_KEYS    = ("msg", "message", "log", "event", ...)
CALLER_KEYS = ("source", "caller", ...)
```

`CALLER_KEYS` 는 호출 위치다. Go slog 의 `"source":{"function":..,"file":..,"line":..}`
객체와 zap 의 `"caller":"consumer/rabbitmq.go:300"` 문자열을 둘 다 받아서
`(rabbitmq.go:300)` 으로 짧게 찍는다. function 경로는 너무 길어서 버린다.

**실제 로그는 손볼 게 없다.** requester 로그가 이 형태인데 그대로 통과한다:

```json
{"time":"2026-09-04T02:19:24.568353422Z","level":"INFO",
 "source":{"function":"...","file":"/consumer/rabbitmq.go","line":300},
 "msg":"handle message start","rid":"a1b2c3d4-...","content_id":"20260904-...@subtitle@...",
 "job_id":73720239,"cpk":"tenant-a"}
```

- `time` / `level` / `msg` 모두 별칭 목록에 이미 있다
- 나노초 9자리(`.568353422Z`)는 `fromisoformat` 이 못 받아서 6자리로 잘라 넘긴다
- `source` 객체는 `(rabbitmq.go:300)` 으로 압축된다
- `content_id` 의 `@` 는 `shlex.quote` 로 안전하게 넘어간다
- rid 가 UUID 라 `grep -F` 오탐이 사실상 없다

실제 환경용 인벤토리는 저장소에 넣지 않는다 (`.gitignore` 처리).
`inventory.example.json` 을 복사해서 각자 만들어 쓴다.

타임스탬프는 ISO8601(`Z`/오프셋/공백 구분), epoch 초·밀리·마이크로·나노를 자동 판별한다.
`⚠ 타임스탬프를 못 읽은 줄` 경고가 뜨면 `TS_KEYS` 에 키를 추가하면 된다.

## 설계상 지켜둔 것들

- **JSON 이 아닌 줄을 버리지 않는다.** panic, 스택트레이스, 기동 배너는 장애 시점에
  제일 보고 싶은 줄이다. 파싱 실패해도 `_raw` 로 살리고, 직전 줄의 시각을 물려받아
  (`~` 표시) 순서가 안 깨지게 한다.
- **한 대가 죽어도 전체가 실패하지 않는다.** 실패한 호스트는 요약에 따로 찍힌다.
  그 죽은 노드가 장애 원인일 때가 많다.
- **구간 갭을 계산해서 보여준다.** 어느 구간에서 시간이 비었는지가 이 도구의 목적이다.
- **`_seq` 로 원래 스트림 순서를 유지한다.** 같은 밀리초에 찍힌 줄들의 인과 순서가
  정렬 때문에 뒤집히지 않는다.

## 다음 단계

`--json` 출력이 있으므로 시각화는 나중에 붙이면 된다. 먼저 터미널 출력으로
**rid→content_id 조인이 실제로 원하는 그림을 그리는지** 확인하는 게 순서다.
조인이 틀렸으면 시각화는 어차피 버리는 코드다.

수집부(`run_ssh` / `build_remote_script`)만 갈아끼우면 나중에 Loki 같은 중앙 로그
스택이 들어와도 정규화·조인·정렬·출력은 그대로 재사용된다.

## 테스트

실제 노드 없이 전체 파이프라인을 검증한다. `test/fakebin/ssh` 가 ssh 를 흉내내
로컬 bash 로 실행하므로 코드 경로는 실제와 동일하다.

```sh
python3 test/make_fixtures.py
PATH="$PWD/test/fakebin:$PATH" ./logtrace.py -i test/inventory.test.json --rid rid-7f3a91
```

픽스처에는 로테이션된 `.gz`, 서로 다른 타임스탬프 키 3종(ISO `Z` / 공백+오프셋 /
epoch ms), 다른 필드에 값이 든 줄, JSON 이 아닌 panic 줄, 시간창 밖의 같은
content_id, 접속 실패 노드가 들어 있다.
