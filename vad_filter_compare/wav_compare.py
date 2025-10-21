import argparse
import os
import sys
import numpy as np

# Try multiple loaders for robustness
def _try_imports():
    loaders = {}
    try:
        from scipy.io import wavfile as scipy_wavfile  # type: ignore
        loaders["scipy"] = scipy_wavfile
    except Exception:
        pass
    try:
        import soundfile as sf  # type: ignore
        loaders["soundfile"] = sf
    except Exception:
        pass
    return loaders

LOADERS = _try_imports()

def load_wav(path, prefer="scipy"):
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    # Prefer scipy, fallback to soundfile
    if prefer == "scipy" and "scipy" in LOADERS:
        sr, data = LOADERS["scipy"].read(path)
        # Convert to float32 in [-1, 1] if integer input
        if np.issubdtype(data.dtype, np.integer):
            info = np.iinfo(data.dtype)
            data = data.astype(np.float32) / max(abs(info.min), info.max)
        else:
            data = data.astype(np.float32)
        return sr, data
    elif "soundfile" in LOADERS:
        data, sr = LOADERS["soundfile"].read(path, always_2d=False, dtype="float32")
        return sr, data
    else:
        raise RuntimeError(
            "No supported WAV loader found. Please install scipy or soundfile.\n"
            "pip install scipy  OR  pip install soundfile"
        )

def to_mono(x):
    # If multichannel, average to mono
    if x.ndim == 2:
        return x.mean(axis=1)
    return x

def align_lengths(a, b):
    n = min(len(a), len(b))
    return a[:n], b[:n]

def rms(x, frame_len):
    if len(x) == 0 or frame_len <= 0:
        return np.array([])
    pad = (frame_len - len(x) % frame_len) % frame_len
    if pad:
        x = np.pad(x, (0, pad), "constant")
    frames = x.reshape(-1, frame_len)
    return np.sqrt((frames**2).mean(axis=1))

def main():
    parser = argparse.ArgumentParser(description="Visual compare two WAV files (original vs processed).")
    parser.add_argument("--orig", required=True, help="Path to original WAV")
    parser.add_argument("--proc", required=True, help="Path to processed WAV")
    parser.add_argument("--start", type=float, default=0.0, help="Start time (seconds) for overlay zoom")
    parser.add_argument("--end", type=float, default=2.0, help="End time (seconds) for overlay zoom")
    parser.add_argument("--rms_window_ms", type=float, default=50.0, help="RMS window size in milliseconds")
    parser.add_argument("--outdir", default="wav_compare_outputs", help="Directory to save plots")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    sr_o, orig = load_wav(args.orig)
    sr_p, proc = load_wav(args.proc)

    # Warn if sample rates differ
    if sr_o != sr_p:
        print(f"[WARN] Sample rates differ: original={sr_o}, processed={sr_p}. Using min(sr).", file=sys.stderr)
    sr = min(sr_o, sr_p)

    # If different SR, resample the higher one down using simple linear interpolation (lightweight)
    def simple_resample(x, sr_from, sr_to):
        if sr_from == sr_to:
            return x
        t_from = np.linspace(0, len(x)/sr_from, num=len(x), endpoint=False)
        n_to = int(np.floor(len(x) * sr_to / sr_from))
        t_to = np.linspace(0, len(x)/sr_from, num=n_to, endpoint=False)
        return np.interp(t_to, t_from, x).astype(np.float32)

    orig = to_mono(orig).astype(np.float32)
    proc = to_mono(proc).astype(np.float32)
    orig = simple_resample(orig, sr_o, sr)
    proc = simple_resample(proc, sr_p, sr)

    # Align lengths for fair comparison
    orig, proc = align_lengths(orig, proc)
    if len(orig) == 0:
        raise RuntimeError("Audio length after alignment is zero. Check your inputs.")

    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend for safe saving
    import matplotlib.pyplot as plt

    # 1) Full waveform - original
    t = np.arange(len(orig)) / sr
    plt.figure()
    plt.plot(t, orig, linewidth=0.8, label="original")
    plt.title("Original waveform (full)")
    plt.xlabel("Time (s)")
    plt.ylabel("Amplitude")
    plt.legend()
    out1 = os.path.join(args.outdir, "01_original_waveform.png")
    plt.savefig(out1, dpi=150, bbox_inches="tight")
    plt.close()

    # 2) Full waveform - processed
    plt.figure()
    plt.plot(t, proc, linewidth=0.8, label="processed")
    plt.title("Processed waveform (full)")
    plt.xlabel("Time (s)")
    plt.ylabel("Amplitude")
    plt.legend()
    out2 = os.path.join(args.outdir, "02_processed_waveform.png")
    plt.savefig(out2, dpi=150, bbox_inches="tight")
    plt.close()

    # 3) Overlay zoomed segment
    start_s = max(0.0, args.start)
    end_s = max(start_s, args.end)
    i0 = int(start_s * sr)
    i1 = int(end_s * sr)
    i1 = min(i1, len(orig))
    if i1 - i0 < 2:
        i0, i1 = 0, min(len(orig), int(2 * sr))  # fallback 2 seconds from start
    tz = np.arange(i0, i1) / sr
    plt.figure()
    plt.plot(tz, orig[i0:i1], linewidth=0.9, label="original")
    plt.plot(tz, proc[i0:i1], linewidth=0.9, alpha=0.8, label="processed")
    plt.title(f"Overlay (zoom) {tz[0]:.3f}s - {tz[-1]:.3f}s")
    plt.xlabel("Time (s)")
    plt.ylabel("Amplitude")
    plt.legend()
    out3 = os.path.join(args.outdir, "03_overlay_zoom.png")
    plt.savefig(out3, dpi=150, bbox_inches="tight")
    plt.close()

    # 4) Difference signal (processed - original)
    diff = proc - orig
    plt.figure()
    plt.plot(t, diff, linewidth=0.8, label="diff = processed - original")
    plt.title("Difference signal (full)")
    plt.xlabel("Time (s)")
    plt.ylabel("Amplitude")
    plt.legend()
    out4 = os.path.join(args.outdir, "04_difference_full.png")
    plt.savefig(out4, dpi=150, bbox_inches="tight")
    plt.close()

    # 5) Segmental RMS before/after (quick look at attenuation effect)
    frame_len = max(1, int(sr * (args.rms_window_ms / 1000.0)))
    rms_o = rms(orig, frame_len)
    rms_p = rms(proc, frame_len)
    x_frames = np.arange(len(rms_o)) * (frame_len / sr)
    plt.figure()
    plt.plot(x_frames, rms_o, linewidth=0.9, label="RMS original")
    plt.plot(x_frames, rms_p, linewidth=0.9, alpha=0.8, label="RMS processed")
    plt.title(f"Segmental RMS (~{args.rms_window_ms:.0f} ms window)")
    plt.xlabel("Time (s)")
    plt.ylabel("RMS amplitude")
    plt.legend()
    out5 = os.path.join(args.outdir, "05_segmental_rms.png")
    plt.savefig(out5, dpi=150, bbox_inches="tight")
    plt.close()

    # Summarize some quick stats
    def db(x):
        eps = 1e-12
        return 20 * np.log10(np.maximum(np.abs(x), eps)).mean()

    overall_db_orig = 20*np.log10(np.maximum(np.sqrt((orig**2).mean()), 1e-12))
    overall_db_proc = 20*np.log10(np.maximum(np.sqrt((proc**2).mean()), 1e-12))
    overall_db_diff = 20*np.log10(np.maximum(np.sqrt((diff**2).mean()), 1e-12))

    summary = os.path.join(args.outdir, "summary.txt")
    with open(summary, "w") as f:
        f.write("=== WAV Compare Summary ===\n")
        f.write(f"Sample rate used: {sr} Hz\n")
        f.write(f"Duration compared: {len(orig)/sr:.3f} s\n")
        f.write(f"RMS level (original): {overall_db_orig:.2f} dBFS\n")
        f.write(f"RMS level (processed): {overall_db_proc:.2f} dBFS\n")
        f.write(f"RMS level (difference): {overall_db_diff:.2f} dBFS\n")
        f.write(f"Overlay window: {start_s:.3f}s - {end_s:.3f}s\n")
        f.write(f"RMS window: {frame_len/sr:.3f} s\n")
    print("Saved:")
    for p in [out1, out2, out3, out4, out5, summary]:
        print(" -", p)

if __name__ == "__main__":
    main()
