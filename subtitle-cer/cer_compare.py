#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import re
import unicodedata
from typing import List, Tuple, Optional

TIME_PATTERN = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2}[,\.]\d{3})"
)

def parse_time_to_sec(t: str) -> float:
    t = t.replace(",", ".")
    hh, mm, ss_ms = t.split(":")
    ss, ms = ss_ms.split(".")
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000.0

def parse_subtitle_file(path: str) -> List[Tuple[Optional[float], Optional[float], str]]:
    """
    Returns list of (start, end, text). start/end can be None for .txt.
    """
    ext = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    if ext == ".txt":
        text = content.strip()
        return [(None, None, text)] if text else []

    # SRT / VTT generic block parsing
    lines = content.splitlines()
    segments = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        match = TIME_PATTERN.search(line)
        if match:
            start = parse_time_to_sec(match.group("start"))
            end = parse_time_to_sec(match.group("end"))
            i += 1
            # collect text lines until blank or next timestamp
            texts = []
            while i < n and not TIME_PATTERN.search(lines[i]) and lines[i].strip() != "":
                # skip pure index lines (common in .srt)
                if not lines[i].strip().isdigit():
                    texts.append(lines[i].strip())
                i += 1
            seg_text = " ".join(texts).strip()
            if seg_text:
                segments.append((start, end, seg_text))
        else:
            i += 1

    if not segments:
        # fallback: if no timestamps recognized, treat whole file as one block
        flat_text = " ".join([ln.strip() for ln in lines if ln.strip() and not ln.strip().isdigit()])
        if flat_text:
            return [(None, None, flat_text)]
    return segments

def merge_segments(segments: List[Tuple[Optional[float], Optional[float], str]],
                   merge_window: float = 1.5) -> List[Tuple[Optional[float], Optional[float], str]]:
    """
    Merge segments if the gap between current.end and next.start <= merge_window (seconds).
    If no times are present, returns the original list.
    """
    if not segments:
        return []
    # If no timestamps for any segment, just return as is
    if all(s[0] is None or s[1] is None for s in segments):
        return segments

    # sort by start time (None at the end)
    segments = sorted(segments, key=lambda x: (float("inf") if x[0] is None else x[0]))

    merged = []
    cur_start, cur_end, cur_text = segments[0]
    for start, end, text in segments[1:]:
        if cur_end is not None and start is not None and (start - cur_end) <= merge_window:
            # merge into current block
            cur_end = max(cur_end, end if end is not None else cur_end)
            if text:
                cur_text = (cur_text + " " + text).strip()
        else:
            merged.append((cur_start, cur_end, cur_text))
            cur_start, cur_end, cur_text = start, end, text
    merged.append((cur_start, cur_end, cur_text))
    return merged

def normalize_text(s: str,
                   case_insensitive: bool = True,
                   strip_punct: bool = True,
                   unicode_form: str = "NFC") -> str:
    # Unicode normalize (avoid Hangul Jamo split issues)
    s = unicodedata.normalize(unicode_form, s)
    # Case-fold (handles more cases than lower())
    if case_insensitive:
        s = s.casefold()
    # Replace multiple whitespace with single space
    s = re.sub(r"\s+", " ", s)
    s = s.strip()
    if strip_punct:
        # Keep letters/numbers/underscore and whitespace; drop punctuation/emojis/symbols
        s = re.sub(r"[^\w\s]", "", s, flags=re.UNICODE)
        s = re.sub(r"\s+", " ", s).strip()
    return s

def to_flat_text(segments: List[Tuple[Optional[float], Optional[float], str]]) -> str:
    # Sort by start time if available, otherwise keep order
    if segments and any(s[0] is not None for s in segments):
        segments = sorted(segments, key=lambda x: (float("inf") if x[0] is None else x[0]))
    return " ".join([t for _, _, t in segments if t]).strip()

def levenshtein_ops(ref: str, hyp: str) -> Tuple[int, int, int, int]:
    """
    Returns (S, D, I, distance) using DP with backtrace.
    """
    n, m = len(ref), len(hyp)
    dp = [[0]*(m+1) for _ in range(n+1)]
    bt = [[None]*(m+1) for _ in range(n+1)]  # 'M'(match/sub), 'D', 'I'

    for i in range(1, n+1):
        dp[i][0] = i
        bt[i][0] = 'D'
    for j in range(1, m+1):
        dp[0][j] = j
        bt[0][j] = 'I'

    for i in range(1, n+1):
        rc = ref[i-1]
        for j in range(1, m+1):
            hc = hyp[j-1]
            cost = 0 if rc == hc else 1
            # substitution or match
            best = dp[i-1][j-1] + cost
            op = 'M'  # match/sub
            # deletion
            if dp[i-1][j] + 1 < best:
                best = dp[i-1][j] + 1
                op = 'D'
            # insertion
            if dp[i][j-1] + 1 < best:
                best = dp[i][j-1] + 1
                op = 'I'
            dp[i][j] = best
            bt[i][j] = op

    # backtrace counts
    i, j = n, m
    S = D = I = 0
    while i > 0 or j > 0:
        op = bt[i][j]
        if op == 'M':
            # match or substitution
            if i > 0 and j > 0 and ref[i-1] != hyp[j-1]:
                S += 1
            i -= 1; j -= 1
        elif op == 'D':
            D += 1
            i -= 1
        elif op == 'I':
            I += 1
            j -= 1
        else:
            # Shouldn't happen, but safeguard
            if i > 0:
                D += 1; i -= 1
            elif j > 0:
                I += 1; j -= 1

    return S, D, I, dp[n][m]

def cer_from_texts(ref_text: str, hyp_text: str) -> Tuple[float, int, int, int, int]:
    """
    Returns (cer, S, D, I, N). cer in [0,1].
    """
    N = max(len(ref_text), 1)  # avoid div by zero
    S, D, I, dist = levenshtein_ops(ref_text, hyp_text)
    cer = dist / N
    return cer, S, D, I, N

def run_eval(ref_path: str, hyp_paths: List[str], merge_window: float,
             case_insensitive: bool, strip_punct: bool, unicode_form: str):
    # Parse and merge segments for each file
    ref_segs = merge_segments(parse_subtitle_file(ref_path), merge_window=merge_window)
    hyps   = [merge_segments(parse_subtitle_file(p), merge_window=merge_window) for p in hyp_paths]

    # Flatten to strings (ordering by time if available)
    ref_text_raw = to_flat_text(ref_segs)
    hyp_texts_raw = [to_flat_text(s) for s in hyps]

    # Normalize
    ref_text = normalize_text(ref_text_raw, case_insensitive=case_insensitive,
                              strip_punct=strip_punct, unicode_form=unicode_form)
    hyp_texts = [normalize_text(t, case_insensitive=case_insensitive,
                                strip_punct=strip_punct, unicode_form=unicode_form)
                 for t in hyp_texts_raw]

    print("=== Settings ===")
    print(f"merge_window: {merge_window}s  | case_insensitive: {case_insensitive}  | strip_punct: {strip_punct}  | unicode_form: {unicode_form}")
    print()
    for idx, hyp_text in enumerate(hyp_texts, start=1):
        cer, S, D, I, N = cer_from_texts(ref_text, hyp_text)
        print(f"[Hypothesis {idx}]  File: {hyp_paths[idx-1]}")
        print(f"  CER: {cer*100:.2f}%  (S={S}, D={D}, I={I}, N={N})  -> Accuracy≈ {(1-cer)*100:.2f}%")
        print()

def main():
    ap = argparse.ArgumentParser(description="Compute CER for two hypotheses vs reference (SRT/VTT/TXT).")
    ap.add_argument("reference", help="Reference subtitle/text file (ground truth).")
    ap.add_argument("hyp1", help="Hypothesis file 1.")
    ap.add_argument("hyp2", help="Hypothesis file 2.")
    ap.add_argument("--merge-window", type=float, default=1.5,
                    help="Merge adjacent segments when the time gap <= this many seconds (default: 1.5).")
    ap.add_argument("--keep-punct", dest="strip_punct", action="store_false",
                    help="Keep punctuation (by default punctuation is stripped).")
    ap.add_argument("--unicode-form", default="NFC", choices=["NFC","NFKC","NFD","NFKD"],
                    help="Unicode normalization form (default: NFC).")
    ap.add_argument("--case-sensitive", dest="case_insensitive", action="store_false",
                    help="Make comparison case-sensitive (default is case-insensitive).")
    args = ap.parse_args()

    run_eval(
        ref_path=args.reference,
        hyp_paths=[args.hyp1, args.hyp2],
        merge_window=args.merge_window,
        case_insensitive=args.case_insensitive,
        strip_punct=args.strip_punct,
        unicode_form=args.unicode_form
    )

if __name__ == "__main__":
    main()
