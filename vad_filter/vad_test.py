#!/usr/bin/env python3
"""
Python VAD Test Script
Go 코드와 동일한 로직으로 VAD 필터링 수행
mp3 -> wav -> vad filter -> webm
"""

import sys
import os
import time
import subprocess
from pathlib import Path
import torch
import torchaudio
from silero_vad import load_silero_vad, get_speech_timestamps


def extract_audio_to_wav(input_path):
    """MP3/MP4를 WAV로 변환 (16kHz, mono)"""
    print(f"오디오 추출 중: {input_path}")
    
    output_path = Path(input_path).with_suffix('.wav')
    
    cmd = [
        'ffmpeg',
        '-i', input_path,
        '-vn',
        '-c:a', 'pcm_s16le',  # 16-bit PCM
        '-ar', '16000',        # 16kHz
        '-ac', '1',            # mono
        '-map_metadata', '-1',
        '-f', 'wav',
        '-y',
        str(output_path)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"FFmpeg 실행 실패: {result.stderr}")
    
    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"추출된 오디오 파일 크기: {file_size_mb:.2f} MB")
    print(f"결과 파일: {output_path}")
    
    return str(output_path)


def vad_filter(wav_path):
    """VAD 필터링 적용"""
    print(f"\n{'='*50}")
    print("VAD 필터링 시작")
    print(f"{'='*50}")
    
    # Silero VAD 모델 로드
    print("Silero VAD 모델 로드 중...")
    model = load_silero_vad()
    
    # 오디오 로드
    print(f"오디오 파일 로드 중: {wav_path}")
    wav, sample_rate = torchaudio.load(wav_path)
    
    # mono로 변환 (혹시 stereo일 경우)
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)
    
    wav = wav.squeeze()
    
    print(f"샘플레이트: {sample_rate} Hz")
    print(f"채널 수: 1 (mono)")
    print(f"총 길이: {len(wav) / sample_rate:.2f}초")
    
    # 데이터 범위 확인
    print(f"🔍 PCM 데이터 범위: min={wav.min():.6f}, max={wav.max():.6f}")
    print(f"🔍 처음 10개 샘플: {wav[:10].tolist()}")
    print(f"🔍 평균 절대값: {wav.abs().mean():.6f}")
    
    # 음성 구간 탐지
    print("\n음성 구간을 탐지하는 중...")
    
    # Go 코드와 동일한 파라미터 사용
    speech_timestamps = get_speech_timestamps(
        wav,
        model,
        threshold=0.5,                    # Go: Threshold
        min_silence_duration_ms=100,      # Go: MinSilenceDurationMs
        speech_pad_ms=30,                 # Go: SpeechPadMs
        min_speech_duration_ms=0,         # 명시: 최소 음성 길이 제한 없음
        max_speech_duration_s=float('inf'),  # 명시: 최대 음성 길이 제한 없음
        return_seconds=True
    )
    
    print(f"탐지된 음성 구간: {len(speech_timestamps)}개")
    print(f"🔍 추가 필터링 파라미터: min_speech_duration_ms=0, max_speech_duration_s=inf")
    
    # 병합 로직 제거 - Python VAD의 원래 결과만 사용
    merged_segments = speech_timestamps
    
    print(f"음성 구간 (병합 없음): {len(merged_segments)}개\n")
    
    # 음성 구간 출력
    for i, segment in enumerate(merged_segments):
        duration = segment['end'] - segment['start']
        print(f"음성 구간 {i+1}: {segment['start']:.2f}s ~ {segment['end']:.2f}s ({duration:.2f}s)")
    
    # 오디오 필터링 (긴 무음만 제거)
    print("\n오디오 필터링 중...")
    processed_audio = wav.clone()
    
    if len(merged_segments) == 0:
        print("⚠️  음성 구간이 발견되지 않았습니다. 전체를 무음 처리합니다.")
        processed_audio[:] = 0.0
    else:
        # 음성 구간 마킹
        speech_mask = torch.zeros(len(wav), dtype=torch.bool)
        
        for segment in merged_segments:
            start_sample = int(segment['start'] * sample_rate)
            end_sample = int(segment['end'] * sample_rate)
            
            # 범위 체크
            start_sample = max(0, start_sample)
            end_sample = min(len(wav), end_sample)
            
            if start_sample < end_sample:
                speech_mask[start_sample:end_sample] = True
        
        # 긴 무음 구간만 제거 (1초 이상)
        long_silence_threshold = 1.0
        silenced_samples = 0
        
        in_silence = False
        silence_start = 0
        
        for i in range(len(processed_audio)):
            if not speech_mask[i]:
                if not in_silence:
                    in_silence = True
                    silence_start = i
                
                # 마지막이거나 다음이 음성이면
                if i == len(processed_audio) - 1 or speech_mask[i + 1]:
                    silence_length = (i - silence_start + 1) / sample_rate
                    
                    # 긴 무음만 0으로 처리
                    if silence_length >= long_silence_threshold:
                        processed_audio[silence_start:i+1] = 0.0
                        silenced_samples += (i - silence_start + 1)
                        print(f"🔇 긴 무음 제거: {silence_start/sample_rate:.2f}s ~ {i/sample_rate:.2f}s ({silence_length:.2f}s)")
                    
                    in_silence = False
        
        original_duration = len(wav) / sample_rate
        speech_duration = speech_mask.sum().item() / sample_rate
        silenced_duration = silenced_samples / sample_rate
        
        print(f"\n📊 처리 결과:")
        print(f"전체 길이: {original_duration:.2f}초 (유지됨)")
        print(f"음성 구간: {speech_duration:.2f}초 ({speech_duration/original_duration*100:.1f}%)")
        print(f"긴 무음 제거: {silenced_duration:.2f}초 ({silenced_duration/original_duration*100:.1f}%)")
        print(f"짧은 무음 유지: {original_duration - speech_duration - silenced_duration:.2f}초")
    
    # 필터링된 WAV 저장
    output_wav_path = str(Path(wav_path).with_stem(Path(wav_path).stem + '_vad_filtered'))
    
    # Float32를 Int16으로 변환
    processed_audio_int16 = (processed_audio * 32767).clamp(-32768, 32767).to(torch.int16)
    
    torchaudio.save(
        output_wav_path,
        processed_audio_int16.unsqueeze(0),
        sample_rate,
        encoding='PCM_S',
        bits_per_sample=16
    )
    
    print(f"\n✅ 처리 완료!")
    print(f"출력 파일: {output_wav_path}")
    print(f"📝 1초 이상 긴 무음만 제거, 짧은 무음은 원본 유지 (타임스탬프 보존)")
    
    return merged_segments, output_wav_path


def extract_audio_to_webm(filtered_wav_path):
    """필터링된 WAV를 WebM으로 변환"""
    print(f"\n오디오 변환 중: WAV -> WebM")
    
    output_path = str(Path(filtered_wav_path).with_stem(
        Path(filtered_wav_path).stem + '_extracted'
    ).with_suffix('.webm'))
    
    cmd = [
        'ffmpeg',
        '-i', filtered_wav_path,
        '-c:a', 'libopus',
        '-b:a', '12k',
        '-application', 'voip',  # 음성 최적화
        '-f', 'webm',
        '-y',
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"FFmpeg 실행 실패: {result.stderr}")
    
    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"추출된 오디오 파일 크기: {file_size_mb:.2f} MB")
    print(f"결과 파일: {output_path}")
    
    return output_path


def main():
    if len(sys.argv) != 2:
        print(f"사용법: {sys.argv[0]} <입력파일.mp3|mp4>")
        sys.exit(1)
    
    input_file = sys.argv[1]
    
    if not os.path.exists(input_file):
        print(f"❌ 파일을 찾을 수 없습니다: {input_file}")
        sys.exit(1)
    
    print(f"{'='*50}")
    print("Python VAD 필터 테스트")
    print(f"{'='*50}")
    print(f"입력 파일: {input_file}\n")
    
    total_start = time.time()
    
    # 1. MP3/MP4 -> WAV
    wav_extract_start = time.time()
    wav_path = extract_audio_to_wav(input_file)
    wav_extract_duration = time.time() - wav_extract_start
    print(f"⏱️  오디오 추출 시간(mp4 to wav): {wav_extract_duration:.2f}초\n")
    
    # 2. VAD 필터링
    filter_start = time.time()
    segments, filtered_wav_path = vad_filter(wav_path)
    filter_duration = time.time() - filter_start
    print(f"\n⏱️  무음구간 변환 시간: {filter_duration:.2f}초")
    
    # 3. WAV -> WebM
    extract_start = time.time()
    webm_path = extract_audio_to_webm(filtered_wav_path)
    extract_duration = time.time() - extract_start
    print(f"\n⏱️  오디오 추출 시간(wav to webm): {extract_duration:.2f}초")
    
    # 전체 실행 시간
    total_duration = time.time() - total_start
    
    print(f"\n{'='*50}")
    print("📊 Results")
    print(f"{'='*50}")
    print(f"오디오 추출(mp4 to wav):    {wav_extract_duration:8.2f}초 ({wav_extract_duration/total_duration*100:5.1f}%)")
    print(f"VAD 필터링:                {filter_duration:8.2f}초 ({filter_duration/total_duration*100:5.1f}%)")
    print(f"오디오 변환(wav to webm):   {extract_duration:8.2f}초 ({extract_duration/total_duration*100:5.1f}%)")
    print(f"{'='*50}")
    print(f"전체 실행 시간:              {total_duration:8.2f}초 (100.0%)")
    
    print(f"\n✅ 모든 처리 완료!")
    print(f"📁 최종 결과 파일: {webm_path}")


if __name__ == '__main__':
    main()
