# analyze_whisper_segments.py
import json
import argparse
import statistics as stats
from pathlib import Path

def load_segments(json_path):
    """OpenAI Whisper verbose_json 형태에서 segments 추출.
    segments[*] = {start, end, text, words?}
    """
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    # data가 list면 그대로, dict면 segments 키 찾기
    segments = data if isinstance(data, list) else data.get("segments", [])

    # 필수 필드만 남김(견고성)
    out = []
    for s in segments:
        start = float(s.get("start", 0.0))
        end   = float(s.get("end", start))
        text  = s.get("text", "")
        words = s.get("words", []) or []
        # words 항목의 start/end 보호
        wnorm = []
        for w in words:
            try:
                wnorm.append({
                    "start": float(w.get("start", start)),
                    "end":   float(w.get("end",   start)),
                    "word":  w.get("word", "").strip()
                })
            except Exception:
                pass
        out.append({"start": start, "end": end, "text": text, "words": wnorm})
    # 시작시간 기준 정렬(방어)
    out.sort(key=lambda s: (s["start"], s["end"]))
    return out

def summarize(segments, short_thr=0.5, tiny_gap_thr=0.2, long_gap_thr=1.0):
    """세그먼트 끊김 품질 요약"""
    n = len(segments)
    if n == 0:
        return {
            "segments": 0, "mean_dur": 0, "median_dur": 0,
            "p10_dur": 0, "p90_dur": 0, "short_ratio": 0,
            "tiny_gap_cnt": 0, "tiny_gap_ratio": 0,
            "gap_p10": 0, "gap_median": 0, "gap_p90": 0,
            "avg_words_per_seg": 0, "worded_segments": 0,
            "coverage_sec": 0, "total_span_sec": 0,
        }

    durs = [max(0.0, s["end"] - s["start"]) for s in segments]
    mean_d = sum(durs)/n
    med_d  = stats.median(durs)
    p10, p90 = stats.quantiles(durs, n=10)[0], stats.quantiles(durs, n=10)[-1]  # 대충 p10/p90

    short_cnt = sum(1 for d in durs if d < short_thr)
    short_ratio = short_cnt / n

    # 세그먼트 간 gap
    gaps = []
    tiny_gap_cnt = 0
    long_gap_cnt = 0
    for i in range(1, n):
        gap = segments[i]["start"] - segments[i-1]["end"]
        # 음수(overlap)면 0으로 클램프(병합된 후처리 가정)
        if gap < 0:
            gap = 0.0
        gaps.append(gap)
        if gap < tiny_gap_thr: tiny_gap_cnt += 1
        if gap >= long_gap_thr: long_gap_cnt += 1

    gap_p10 = gap_med = gap_p90 = 0.0
    if gaps:
        gap_med = stats.median(gaps)
        q = stats.quantiles(gaps, n=10)
        gap_p10, gap_p90 = q[0], q[-1]

    tiny_gap_ratio = (tiny_gap_cnt / max(1, len(gaps))) if gaps else 0.0

    # 워드 통계(옵션)
    word_counts = []
    worded_segments = 0
    for s in segments:
        wc = len(s.get("words", []) or [])
        if wc > 0:
            worded_segments += 1
            word_counts.append(wc)
    avg_words = (sum(word_counts)/worded_segments) if worded_segments else 0.0

    coverage_sec = sum(durs)
    total_span_sec = segments[-1]["end"] - segments[0]["start"]

    return {
        "segments": n,
        "mean_dur": round(mean_d, 3),
        "median_dur": round(med_d, 3),
        "p10_dur": round(p10, 3),
        "p90_dur": round(p90, 3),
        "short_thr": short_thr,
        "short_ratio": round(short_ratio, 4),
        "short_cnt": short_cnt,

        "tiny_gap_thr": tiny_gap_thr,
        "tiny_gap_cnt": tiny_gap_cnt,
        "tiny_gap_ratio": round(tiny_gap_ratio, 4),
        "long_gap_thr": long_gap_thr,
        "long_gap_cnt": long_gap_cnt,

        "gap_p10": round(gap_p10, 3),
        "gap_median": round(gap_med, 3),
        "gap_p90": round(gap_p90, 3),

        "avg_words_per_seg": round(avg_words, 2),
        "worded_segments": worded_segments,

        "coverage_sec": round(coverage_sec, 3),
        "total_span_sec": round(total_span_sec, 3),
    }

def print_report(path, summ):
    print(f"\n=== Whisper Segment Report: {path} ===")
    print(f"segments                 : {summ['segments']}")
    print(f"mean_dur / median        : {summ['mean_dur']} s / {summ['median_dur']} s")
    print(f"dur p10 / p90            : {summ['p10_dur']} s / {summ['p90_dur']} s")
    print(f"short(<{summ['short_thr']}s) : {summ['short_cnt']} ({summ['short_ratio']*100:.1f}%)")
    print(f"gaps p10/median/p90      : {summ['gap_p10']} / {summ['gap_median']} / {summ['gap_p90']} s")
    print(f"tiny gaps(<{summ['tiny_gap_thr']}s) : {summ['tiny_gap_cnt']} "
          f"({summ['tiny_gap_ratio']*100:.1f}%)")
    print(f"long gaps(>={summ['long_gap_thr']}s): {summ['long_gap_cnt']}")
    print(f"avg words / segment      : {summ['avg_words_per_seg']}  "
          f"(segments with words: {summ['worded_segments']})")
    print(f"coverage / total span    : {summ['coverage_sec']} s / {summ['total_span_sec']} s")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json", nargs="+", help="Whisper verbose_json 파일 경로(1개 이상). 여러 개 주면 A/B 비교용으로 각각 요약 출력.")
    ap.add_argument("--short_thr", type=float, default=0.5, help="짧은 세그먼트 임계(초) [default: 0.5s]")
    ap.add_argument("--tiny_gap_thr", type=float, default=0.2, help="연속성 tiny gap 임계(초) [default: 0.2s]")
    ap.add_argument("--long_gap_thr", type=float, default=1.0, help="긴 멈춤 판정 임계(초) [default: 1.0s]")
    args = ap.parse_args()

    for p in args.json:
        segs = load_segments(p)
        summ = summarize(segs, args.short_thr, args.tiny_gap_thr, args.long_gap_thr)
        print_report(p, summ)

if __name__ == "__main__":
    main()
