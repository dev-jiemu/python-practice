import json
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

# mac 한글 폰트 설정
plt.rcParams['font.family'] = 'AppleGothic'
plt.rcParams['axes.unicode_minus'] = False  # 마이너스 기호 깨짐 방지

LOG_FILE = "scheduler.log"

records = []

with open(LOG_FILE, "r") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue

        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        # scheduler metrics 로그만 필터링
        if obj.get("msg") != "scheduler metrics":
            continue

        metrics = obj.get("metrics", {})
        allocates = metrics.get("request_allocates", [])
        if not allocates:
            continue

        time_str = obj.get("time", "")
        ts = datetime.fromisoformat(time_str)

        for item in allocates:
            records.append({
                "time": ts,
                "cpk": item["cpk"],
                "count": item["count"],
                "pending": item["pending"],
                "queued_at_start": item.get("queued_at_start", 0),  # 없으면 0
            })

df = pd.DataFrame(records)
if df.empty:
    print("No records found")
    exit()

fig, axes = plt.subplots(4, 1, figsize=(14, 28), sharex=False)

# total count
df["total"] = df["count"] + df["pending"]

pivot_count = df.pivot_table(index="time", columns="cpk", values="count", aggfunc="sum").fillna(0)
pivot_pending = df.pivot_table(index="time", columns="cpk", values="pending", aggfunc="sum").fillna(0)
pivot_total = df.pivot_table(index="time", columns="cpk", values="total", aggfunc="sum").fillna(0)
pivot_queued = df.pivot_table(index="time", columns="cpk", values="queued_at_start", aggfunc="sum").fillna(0)

# cpk별 색상 설정
all_cpks = df["cpk"].unique()
base_colors = plt.cm.tab10.colors
color_map = {cpk: base_colors[i % len(base_colors)] for i, cpk in enumerate(all_cpks)}
colors = [color_map[cpk] for cpk in pivot_count.columns]

pivot_count.plot(kind="bar", stacked=True, ax=axes[0], legend=True, color=colors)
pivot_pending.plot(kind="bar", stacked=True, ax=axes[1], legend=True, color=colors)
pivot_total.plot(kind="bar", stacked=True, ax=axes[2], legend=True, color=colors)
pivot_queued.plot(kind="bar", stacked=True, ax=axes[3], legend=True, color=colors)

for ax in axes:
    ax.set_xticklabels([t.strftime('%H:%M:%S') for t in pivot_count.index], rotation=45, ha='right')
    for bars in ax.containers:
        ax.bar_label(bars, label_type='center', fontsize=8)

axes[0].set_title("CPK별 배치 할당량 (count)")
axes[0].set_ylabel("count")
axes[0].legend()

axes[1].set_title("CPK별 처리 중 (pending)")
axes[1].set_ylabel("pending")
axes[1].legend()

axes[2].set_title("CPK별 총 요청 (count + pending)")
axes[2].set_ylabel("total")
axes[2].legend()

axes[3].set_title("CPK별 배치 시작 시점 DB 잔여량 (queued_at_start)")
axes[3].set_ylabel("queued_at_start")
axes[3].legend()

plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig("allocates.png", dpi=150)
print("저장완료: allocates.png")
