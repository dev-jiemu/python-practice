"""원격 실행.

원격에서는 grep -F 로 "싸고 관대한" 프리필터만 한다. jq 에 의존하지 않는다.
접속은 시스템 ssh 바이너리를 exec 하므로 ~/.ssh/config, ssh-agent, ProxyJump,
known_hosts 를 전부 OS 가 처리한다 — 이 코드는 IP 도 패스워드도 알지 못한다.
"""

import concurrent.futures as futures
import shlex
import subprocess

from .records import normalize


DEFAULT_SSH_OPTS = [
    "-o", "BatchMode=yes",        # 패스워드 프롬프트로 매달리지 말고 즉시 실패
    "-o", "ConnectTimeout=10",
    "-o", "LogLevel=ERROR",
]


def build_remote_script(sources, pattern, after=0):
    """원격 bash 로 넘길 스크립트를 만든다.

    - glob 은 원격 셸이 확장해야 하므로 따옴표로 감싸지 않는다.
      (그래서 경로에 $VAR 를 쓰면 원격에서 확장된다 — 의도된 동작이다.)
    - .gz 는 gzip -cd 로 풀어서 grep 한다. zgrep/zcat 은 배포판마다 없을 수 있다.
    - 각 줄 앞에 파일 경로를 탭으로 붙여서 어느 파일에서 나왔는지 잃지 않는다.
    - grep 이 못 찾으면 exit 1 이라 스크립트 전체가 실패로 보이므로 마지막에 exit 0.
    """
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
    """한 호스트에서 스크립트를 실행한다. 실패해도 예외를 밖으로 던지지 않는다."""
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


def collect(targets, ssh_opts, timeout, workers, after, dry_run, embed=True):
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
                # 한 대가 죽어도 전체를 실패시키지 않는다.
                # 오히려 그 죽은 노드가 장애 원인일 때가 많다.
                errors.append((area, host, err))
            if stdout:
                records.extend(normalize(area, host, stdout, field, value, embed))

    return records, errors
