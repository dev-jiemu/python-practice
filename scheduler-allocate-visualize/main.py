import json
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

plt.rcParams['font.family'] = 'AppleGothic'
plt.rcParams['axes.unicode_minus'] = False

LOG_FILE = "scheduler.log"

allocate_records = []
summary_records = []

# summary, allocate 로그 분할로 인해 둘이 나눠서 처리
# summary 흐름 보여주는 차트 하나 추가하면 좋을듯 ㅇㅇ

with open(LOG_FILE, "r") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if obj.get("msg") != "metric":
            continue

        time_str = obj.get("time", "")
        ts = datetime.fromisoformat(time_str)
        metric_type = obj.get("metric_type", "")

        if metric_type == "cpk_allocate":
            allocate_records.append({
                "time": ts,
                "cpk": obj["cpk"],
                "count": obj.get("request_count", 0),   # 필드명 변경 반영
                "pending": obj.get("ongoing_count", 0), # 필드명 변경 반영
                "queued_at_start": obj.get("queued_at_start", 0),
            })

        elif metric_type == "batch_summary":
            batch_id = obj.get("batch_id", "")
            for cpk in obj.get("balanced_cpks", []):
                summary_records.append({"time": ts, "batch_id": batch_id, "cpk": cpk, "type": "balanced"})
            for cpk in obj.get("dedicated_cpks", []):
                summary_records.append({"time": ts, "batch_id": batch_id, "cpk": cpk, "type": "dedicated"})
            for cpk in obj.get("shared_cpks", []):
                summary_records.append({"time": ts, "batch_id": batch_id, "cpk": cpk, "type": "shared"})

# ── 그래프 구성 ──────────────────────────────────────────
has_allocate = bool(allocate_records)
has_summary = bool(summary_records)

n_plots = (4 if has_allocate else 0) + (1 if has_summary else 0)
if n_plots == 0:
    print("No records found")
    exit()

fig, axes = plt.subplots(n_plots, 1, figsize=(14, n_plots * 7), sharex=False)
if n_plots == 1:
    axes = [axes]

ax_idx = 0

if has_allocate:
    df = pd.DataFrame(allocate_records)
    df["total"] = df["count"] + df["pending"]

    pivot_count   = df.pivot_table(index="time", columns="cpk", values="count",          aggfunc="sum").fillna(0)
    pivot_pending = df.pivot_table(index="time", columns="cpk", values="pending",         aggfunc="sum").fillna(0)
    pivot_total   = df.pivot_table(index="time", columns="cpk", values="total",           aggfunc="sum").fillna(0)
    pivot_queued  = df.pivot_table(index="time", columns="cpk", values="queued_at_start", aggfunc="sum").fillna(0)

    all_cpks = df["cpk"].unique()
    base_colors = plt.cm.tab10.colors
    color_map = {cpk: base_colors[i % len(base_colors)] for i, cpk in enumerate(all_cpks)}
    colors = [color_map[cpk] for cpk in pivot_count.columns]

    time_labels = [t.strftime('%H:%M:%S') for t in pivot_count.index]

    for pivot, title, ylabel in [
        (pivot_count,   "CPK별 배치 할당량 (request_count)",          "count"),
        (pivot_pending, "CPK별 처리 중 (ongoing_count)",              "pending"),
        (pivot_total,   "CPK별 총 요청 (count + pending)",            "total"),
        (pivot_queued,  "CPK별 배치 시작 시점 DB 잔여량 (queued_at_start)", "queued_at_start"),
    ]:
        ax = axes[ax_idx]
        pivot.plot(kind="bar", stacked=True, ax=ax, color=colors)
        ax.set_xticklabels(time_labels, rotation=45, ha='right')
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.legend()
        for bars in ax.containers:
            ax.bar_label(bars, label_type='center', fontsize=8)
        ax_idx += 1

if has_summary:
    ds = pd.DataFrame(summary_records)
    # 배치별로 각 type에 속한 cpk 수를 카운트
    pivot_s = ds.pivot_table(index="time", columns="type", values="cpk", aggfunc="count").fillna(0)
    # 컬럼 순서 고정
    for col in ["balanced", "dedicated", "shared"]:
        if col not in pivot_s.columns:
            pivot_s[col] = 0
    pivot_s = pivot_s[["balanced", "dedicated", "shared"]]

    type_colors = {"balanced": "#4C72B0", "dedicated": "#DD8452", "shared": "#55A868"}
    colors_s = [type_colors[c] for c in pivot_s.columns]

    ax = axes[ax_idx]
    pivot_s.plot(kind="bar", stacked=True, ax=ax, color=colors_s)
    ax.set_xticklabels([t.strftime('%H:%M:%S') for t in pivot_s.index], rotation=45, ha='right')
    ax.set_title("배치별 CPK 분류 현황 (balanced / dedicated / shared)")
    ax.set_ylabel("CPK 수")
    ax.legend()
    for bars in ax.containers:
        ax.bar_label(bars, label_type='center', fontsize=8)

plt.tight_layout()
plt.savefig("allocates.png", dpi=150)
print("저장완료: allocates.png")