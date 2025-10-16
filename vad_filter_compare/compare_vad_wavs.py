# 필터 적용한 두 wav 파일 세그먼트 비교
# compare_vad_wavs.py
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly
import argparse

# ---------- util: io / preprocess ----------
def load_mono_16k(path):
    sr, x = wavfile.read(path)  # int16 or float32
    x = x.astype(np.float32)
    # scale to [-1,1] if int16
    if x.dtype != np.float32:
        x = x / 32768.0
    # stereo -> mono
    if x.ndim == 2:
        x = x.mean(axis=1)
    # resample to 16k if needed
    if sr != 16000:
        # resample_poly keeps timing stable
        g = np.gcd(sr, 16000)
        up, down = 16000 // g, sr // g
        x = resample_poly(x, up, down).astype(np.float32)
        sr = 16000
    return sr, x

def moving_rms_mask(x, sr, win_ms=20, eps=1e-4):
    """무음=거의 0인 파일에서 경계 안정화를 위해 이동 RMS로 마스크 생성."""
    win = max(1, int(sr * win_ms / 1000))
    pad = win // 2
    x2 = np.pad(x**2, (pad, pad), mode="constant")
    cumsum = np.cumsum(x2)
    rms2 = (cumsum[win:] - cumsum[:-win]) / win
    rms = np.sqrt(rms2 + 1e-12)
    m = (rms >= eps).astype(np.uint8)
    # 길이 맞추기
    if len(m) < len(x):
        m = np.pad(m, (0, len(x)-len(m)), constant_values=0)
    elif len(m) > len(x):
        m = m[:len(x)]
    return m

# ---------- util: alignment ----------
def best_offset(a, b, max_shift_ms, sr):
    """±max_shift_ms 범위에서 교차상관 최대가 되는 오프셋(샘플)을 찾음.
       양수면 b가 앞으로(=b를 왼쪽으로) 이동."""
    max_shift = int(sr * max_shift_ms / 1000)
    best_sh, best_score = 0, -1
    for sh in range(-max_shift, max_shift + 1):
        if sh >= 0:
            a_seg = a[:len(a)-sh]
            b_seg = b[sh:]
        else:
            a_seg = a[-sh:]
            b_seg = b[:len(b)+sh]
        if len(a_seg) == 0:
            continue
        score = int(np.sum(a_seg & b_seg))
        if score > best_score:
            best_score, best_sh = score, sh
    return best_sh

def shift_mask(m, sh):
    if sh == 0:
        return m
    out = np.zeros_like(m)
    if sh > 0:
        out[:len(m)-sh] = m[sh:]
    else:
        out[-sh:] = m[:len(m)+sh]
    return out

# ---------- util: metrics / diffs ----------
def segments_from_mask(m, sr):
    segs = []
    i = 0
    n = len(m)
    while i < n:
        while i < n and m[i] == 0:
            i += 1
        if i >= n:
            break
        s = i
        while i < n and m[i] == 1:
            i += 1
        e = i
        segs.append((s/sr, e/sr))
    return segs

def runs(mask):
    runs = []
    n = len(mask); i = 0
    while i < n:
        while i < n and mask[i] == 0:
            i += 1
        if i >= n:
            break
        s = i
        while i < n and mask[i] == 1:
            i += 1
        runs.append((s, i-s))
    return runs

def compare_masks(go_m, py_m, sr, topn=15):
    inter = int(np.sum(go_m & py_m))
    uni   = int(np.sum(go_m | py_m))
    go_n  = int(np.sum(go_m))
    py_n  = int(np.sum(py_m))
    iou = inter / uni if uni else 1.0
    prec = inter / go_n if go_n else 1.0
    rec  = inter / py_n if py_n else 1.0

    go_only = (go_m == 1) & (py_m == 0)
    py_only = (go_m == 0) & (py_m == 1)

    go_runs = sorted(runs(go_only), key=lambda t:t[1], reverse=True)
    py_runs = sorted(runs(py_only), key=lambda t:t[1], reverse=True)

    def fmt_runs(rs):
        out = []
        for s, d in rs[:topn]:
            out.append(dict(start_sec=round(s/sr,2), dur_ms=round(1000*d/sr,1)))
        return out

    return dict(
        iou=round(iou,4),
        precision=round(prec,4),
        recall=round(rec,4),
        go_ms=round(1000*go_n/sr,1),
        py_ms=round(1000*py_n/sr,1),
        symm_diff_ms=round(1000*(go_n + py_n - 2*inter)/sr,1),
        go_only_top=fmt_runs(go_runs),
        py_only_top=fmt_runs(py_runs),
    )

# ---------- main ----------
def main(path_go, path_py, eps=1e-4, win_ms=20, align_ms=500):
    sr_go, x_go = load_mono_16k(path_go)
    sr_py, x_py = load_mono_16k(path_py)
    assert sr_go == sr_py == 16000
    n = min(len(x_go), len(x_py))
    x_go, x_py = x_go[:n], x_py[:n]

    go_m0 = moving_rms_mask(x_go, 16000, win_ms=win_ms, eps=eps)
    py_m0 = moving_rms_mask(x_py, 16000, win_ms=win_ms, eps=eps)

    # 정렬
    sh = best_offset(go_m0, py_m0, max_shift_ms=align_ms, sr=16000)
    py_m = shift_mask(py_m0, sh)
    go_m = go_m0

    res = compare_masks(go_m, py_m, 16000, topn=15)

    print("== VAD Mask Comparison ==")
    print(f"Aligned by shift {sh} samples ({sh/16000:.3f} s)")
    print(f"IoU={res['iou']}, Precision={res['precision']}, Recall={res['recall']}")
    print(f"Go speech ms={res['go_ms']}, Py speech ms={res['py_ms']}, Symmetric diff ms={res['symm_diff_ms']}")
    print("\nTop Go-only segments (start_sec, dur_ms):")
    for r in res['go_only_top']: print(r)
    print("\nTop Py-only segments (start_sec, dur_ms):")
    for r in res['py_only_top']: print(r)

    # 필요하면 CSV도 저장
    go_segs = segments_from_mask(go_m, 16000)
    py_segs = segments_from_mask(py_m, 16000)
    np.savetxt("go_segments.csv", np.array(go_segs), fmt="%.3f", delimiter=",", header="start_sec,end_sec", comments="")
    np.savetxt("py_segments.csv", np.array(py_segs), fmt="%.3f", delimiter=",", header="start_sec,end_sec", comments="")
    np.savetxt("go_only_runs.csv", np.array([[r['start_sec'], r['dur_ms']] for r in res['go_only_top']]),
               fmt="%.3f", delimiter=",", header="start_sec,dur_ms", comments="")
    np.savetxt("py_only_runs.csv", np.array([[r['start_sec'], r['dur_ms']] for r in res['py_only_top']]),
               fmt="%.3f", delimiter=",", header="start_sec,dur_ms", comments="")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--go_wav", required=True)
    ap.add_argument("--py_wav", required=True)
    ap.add_argument("--eps", type=float, default=1e-4, help="무음 판정 임계 (RMS)")
    ap.add_argument("--win_ms", type=int, default=20, help="RMS 창(ms)")
    ap.add_argument("--align_ms", type=int, default=500, help="정렬 탐색 범위(ms)")
    args = ap.parse_args()
    main(args.go_wav, args.py_wav, eps=args.eps, win_ms=args.win_ms, align_ms=args.align_ms)
