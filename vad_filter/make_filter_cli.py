#!/usr/bin/env python3
"""
VAD-only CLI
- 입력: WAV
- 처리: Silero VAD로 음성 구간 탐지 + 1초 이상 무음만 0 처리 (길이는 유지)
- 출력: 필터링된 WAV, 음성 구간(JSON)
"""

import argparse
import json
import os
from pathlib import Path

import torch
import torchaudio
from silero_vad import load_silero_vad, get_speech_timestamps


def ensure_mono(wav: torch.Tensor) -> torch.Tensor:
    # (channels, samples) -> mono (samples,)
    if wav.dim() == 2 and wav.size(0) > 1:
        wav = wav.mean(dim=0, keepdim=True)
    if wav.dim() == 2:
        wav = wav.squeeze(0)
    return wav


def resample_if_needed(wav: torch.Tensor, sr: int, target_sr: int) -> (torch.Tensor, int):
    if sr == target_sr:
        return wav, sr
    wav = wav.unsqueeze(0)  # (1, samples)
    wav = torchaudio.functional.resample(wav, orig_freq=sr, new_freq=target_sr)
    return wav.squeeze(0), target_sr


def vad_filter_only(
        in_wav_path: str,
        out_wav_path: str,
        out_segments_path: str | None = None,
        target_sr: int = 16000,
        threshold: float = 0.5,
        min_sil_ms: int = 100,
        pad_ms: int = 30,
        long_sil_threshold_s: float = 1.0,
):
    # 1) 모델 로드
    model = load_silero_vad()

    # 2) 오디오 로드
    wav, sr = torchaudio.load(in_wav_path)  # (channels, samples)
    wav = ensure_mono(wav)
    wav = wav.to(torch.float32)

    # 3) 필요 시 리샘플 (Silero는 8k 또는 16k 권장)
    wav, sr = resample_if_needed(wav, sr, target_sr)

    # 4) 음성 구간 탐지
    speech_timestamps = get_speech_timestamps(
        wav,
        model,
        threshold=threshold,
        min_silence_duration_ms=min_sil_ms,
        speech_pad_ms=pad_ms,
        min_speech_duration_ms=0,
        max_speech_duration_s=float("inf"),
        return_seconds=True,  # start/end를 초 단위로 받음
        sampling_rate=sr,     # 최신 silero_vad는 인자로 받아도 동작 (하위호환)
    )

    # 5) 긴 무음(>= long_sil_threshold_s)만 0으로 처리 (길이는 유지)
    processed = wav.clone()
    if len(speech_timestamps) == 0:
        processed[:] = 0.0
    else:
        speech_mask = torch.zeros(processed.numel(), dtype=torch.bool)
        for seg in speech_timestamps:
            s = max(0, int(seg["start"] * sr))
            e = min(processed.numel(), int(seg["end"] * sr))
            if s < e:
                speech_mask[s:e] = True

        in_sil = False
        sil_start = 0
        silenced = 0
        for i in range(processed.numel()):
            if not speech_mask[i]:
                if not in_sil:
                    in_sil = True
                    sil_start = i

                is_last = (i == processed.numel() - 1)
                next_is_speech = (not is_last and speech_mask[i + 1])
                if is_last or next_is_speech:
                    sil_len_s = (i - sil_start + 1) / sr
                    if sil_len_s >= long_sil_threshold_s:
                        processed[sil_start:i + 1] = 0.0
                        silenced += (i - sil_start + 1)
                    in_sil = False

    # 6) 출력 경로 준비
    out_wav = Path(out_wav_path)
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    if out_segments_path is None:
        out_segments = out_wav.with_suffix(".json")
    else:
        out_segments = Path(out_segments_path)
        out_segments.parent.mkdir(parents=True, exist_ok=True)

    # 7) 세그먼트 JSON 저장 (초 단위 start/end/duration)
    segments_payload = [
        {
            "start": float(seg["start"]),
            "end": float(seg["end"]),
            "duration": float(seg["end"] - seg["start"]),
        }
        for seg in speech_timestamps
    ]
    with open(out_segments, "w", encoding="utf-8") as f:
        json.dump(
            {
                "sample_rate": sr,
                "num_segments": len(segments_payload),
                "segments": segments_payload,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    # 8) WAV 저장 (int16 PCM)
    processed_i16 = (processed * 32767.0).clamp(-32768, 32767).to(torch.int16)
    torchaudio.save(
        str(out_wav),
        processed_i16.unsqueeze(0),
        sr,
        encoding="PCM_S",
        bits_per_sample=16,
    )

    return str(out_wav), str(out_segments)


def parse_args():
    ap = argparse.ArgumentParser(description="Run VAD filter and export segments JSON")
    ap.add_argument("--in", dest="in_path", required=True, help="입력 WAV 경로")
    ap.add_argument("--out-audio", required=True, help="필터링된 WAV 출력 경로")
    ap.add_argument("--out-segments", help="세그먼트 JSON 경로 (미지정 시 out-audio와 같은 스템의 .json)")
    ap.add_argument("--sr", type=int, default=16000, help="내부 처리 샘플레이트 (default: 16000)")
    ap.add_argument("--threshold", type=float, default=0.5, help="VAD 임계값")
    ap.add_argument("--min-sil-ms", type=int, default=100, help="VAD: 최소 무음(ms)")
    ap.add_argument("--pad-ms", type=int, default=30, help="VAD: 패딩(ms)")
    ap.add_argument("--long-sil-threshold", type=float, default=1.0, help="이상 길이의 무음을 0으로 처리(초)")
    return ap.parse_args()


def main():
    args = parse_args()

    if not os.path.exists(args.in_path):
        raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {args.in_path}")

    out_wav, out_json = vad_filter_only(
        in_wav_path=args.in_path,
        out_wav_path=args.out_audio,
        out_segments_path=args.out_segments,
        target_sr=args.sr,
        threshold=args.threshold,
        min_sil_ms=args.min_sil_ms,
        pad_ms=args.pad_ms,
        long_sil_threshold_s=args.long_sil_threshold,
    )

    print("✅ 완료")
    print(f"• 출력 WAV: {out_wav}")
    print(f"• 세그먼트 JSON: {out_json}")


if __name__ == "__main__":
    main()
