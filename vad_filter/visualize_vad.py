#!/usr/bin/env python3
"""
VAD 결과 시각화 - Go vs Python 비교
"""

import sys
import re
import matplotlib.pyplot as plt
import numpy as np
import torchaudio
import platform
from pathlib import Path

# 운영체제별 한글 폰트 자동 설정
system = platform.system()
if system == 'Windows':
    plt.rcParams['font.family'] = 'Malgun Gothic'
elif system == 'Darwin':  # Mac OS
    plt.rcParams['font.family'] = 'AppleGothic'
else:  # Linux
    plt.rcParams['font.family'] = 'NanumGothic'

plt.rcParams['axes.unicode_minus'] = False


def parse_segments_from_log(log_file):
    """로그 파일에서 음성 구간 파싱"""
    segments = []
    
    # 여러 인코딩 시도
    encodings = ['utf-8', 'utf-8-sig', 'cp949', 'euc-kr', 'latin-1']
    content = None
    
    for encoding in encodings:
        try:
            with open(log_file, 'r', encoding=encoding) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue
    
    if content is None:
        # 모든 인코딩 실패시 바이너리로 읽고 에러 무시
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    
    # "음성 구간 N: X.XXs ~ Y.YYs" 패턴 찾기
    pattern = r'음성 구간 \d+: ([\d.]+)s ~ ([\d.]+)s'
    
    for match in re.finditer(pattern, content):
        start = float(match.group(1))
        end = float(match.group(2))
        segments.append((start, end))
    
    return segments


def visualize_vad_comparison(wav_path, go_log, python_log, output_image='vad_comparison.png'):
    """VAD 결과 비교 시각화"""
    
    print("오디오 파일 로드 중...")
    wav, sample_rate = torchaudio.load(wav_path)
    
    # mono로 변환
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0)
    else:
        wav = wav.squeeze()
    
    wav_numpy = wav.numpy()
    duration = len(wav_numpy) / sample_rate
    time_axis = np.linspace(0, duration, len(wav_numpy))
    
    print("로그 파일 파싱 중...")
    go_segments = parse_segments_from_log(go_log)
    python_segments = parse_segments_from_log(python_log)
    
    print(f"Go 음성 구간: {len(go_segments)}개")
    print(f"Python 음성 구간: {len(python_segments)}개")
    
    # 시각화
    fig, axes = plt.subplots(3, 1, figsize=(20, 12))
    
    # 1. 원본 오디오 파형
    axes[0].plot(time_axis, wav_numpy, linewidth=0.5, color='gray', alpha=0.5)
    axes[0].set_title('원본 오디오 파형', fontsize=14, fontweight='bold')
    axes[0].set_ylabel('진폭')
    axes[0].set_xlim(0, duration)
    axes[0].grid(True, alpha=0.3)
    
    # 2. Go VAD 결과
    axes[1].plot(time_axis, wav_numpy, linewidth=0.5, color='gray', alpha=0.3)
    for start, end in go_segments:
        axes[1].axvspan(start, end, alpha=0.3, color='blue', label='음성 구간' if start == go_segments[0][0] else '')
    axes[1].set_title(f'Go VAD 결과 ({len(go_segments)}개 구간)', fontsize=14, fontweight='bold', color='blue')
    axes[1].set_ylabel('진폭')
    axes[1].set_xlim(0, duration)
    axes[1].grid(True, alpha=0.3)
    if go_segments:
        axes[1].legend(loc='upper right')
    
    # 3. Python VAD 결과
    axes[2].plot(time_axis, wav_numpy, linewidth=0.5, color='gray', alpha=0.3)
    for start, end in python_segments:
        axes[2].axvspan(start, end, alpha=0.3, color='red', label='음성 구간' if start == python_segments[0][0] else '')
    axes[2].set_title(f'Python VAD 결과 ({len(python_segments)}개 구간)', fontsize=14, fontweight='bold', color='red')
    axes[2].set_xlabel('시간 (초)')
    axes[2].set_ylabel('진폭')
    axes[2].set_xlim(0, duration)
    axes[2].grid(True, alpha=0.3)
    if python_segments:
        axes[2].legend(loc='upper right')
    
    plt.tight_layout()
    
    print(f"\n시각화 저장 중: {output_image}")
    plt.savefig(output_image, dpi=150, bbox_inches='tight')
    print(f"✅ 저장 완료: {output_image}")
    
    # 통계 출력
    print("\n" + "="*60)
    print("📊 통계")
    print("="*60)
    
    go_total_duration = sum(end - start for start, end in go_segments)
    python_total_duration = sum(end - start for start, end in python_segments)
    
    print(f"전체 길이: {duration:.2f}초")
    print(f"\nGo:")
    print(f"  음성 구간: {len(go_segments)}개")
    print(f"  음성 총 길이: {go_total_duration:.2f}초 ({go_total_duration/duration*100:.1f}%)")
    print(f"\nPython:")
    print(f"  음성 구간: {len(python_segments)}개")
    print(f"  음성 총 길이: {python_total_duration:.2f}초 ({python_total_duration/duration*100:.1f}%)")
    
    # 차이
    diff_segments = len(go_segments) - len(python_segments)
    diff_duration = go_total_duration - python_total_duration
    
    print(f"\n차이:")
    print(f"  구간 개수: {diff_segments:+d}개")
    print(f"  음성 길이: {diff_duration:+.2f}초 ({diff_duration/duration*100:+.1f}%)")
    
    return fig


def visualize_vad_detail(wav_path, go_log, python_log, start_time, end_time, output_image='vad_detail.png'):
    """특정 구간 상세 비교"""
    
    print(f"\n구간 {start_time}s ~ {end_time}s 상세 비교 중...")
    
    wav, sample_rate = torchaudio.load(wav_path)
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0)
    else:
        wav = wav.squeeze()
    
    wav_numpy = wav.numpy()
    
    # 구간 추출
    start_sample = int(start_time * sample_rate)
    end_sample = int(end_time * sample_rate)
    
    wav_section = wav_numpy[start_sample:end_sample]
    time_axis = np.linspace(start_time, end_time, len(wav_section))
    
    go_segments = parse_segments_from_log(go_log)
    python_segments = parse_segments_from_log(python_log)
    
    # 해당 구간에 해당하는 segments만 필터링
    go_segments = [(s, e) for s, e in go_segments if s < end_time and e > start_time]
    python_segments = [(s, e) for s, e in python_segments if s < end_time and e > start_time]
    
    # 시각화
    fig, axes = plt.subplots(2, 1, figsize=(20, 8))
    
    # Go
    axes[0].plot(time_axis, wav_section, linewidth=0.8, color='black')
    for start, end in go_segments:
        axes[0].axvspan(max(start, start_time), min(end, end_time), 
                       alpha=0.3, color='blue')
    axes[0].set_title(f'Go VAD - {start_time}s ~ {end_time}s', fontsize=12, fontweight='bold')
    axes[0].set_ylabel('진폭')
    axes[0].grid(True, alpha=0.3)
    
    # Python
    axes[1].plot(time_axis, wav_section, linewidth=0.8, color='black')
    for start, end in python_segments:
        axes[1].axvspan(max(start, start_time), min(end, end_time), 
                       alpha=0.3, color='red')
    axes[1].set_title(f'Python VAD - {start_time}s ~ {end_time}s', fontsize=12, fontweight='bold')
    axes[1].set_xlabel('시간 (초)')
    axes[1].set_ylabel('진폭')
    axes[1].grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_image, dpi=150, bbox_inches='tight')
    print(f"✅ 상세 이미지 저장: {output_image}")
    
    return fig


def main():
    if len(sys.argv) < 4:
        print("사용법:")
        print(f"  {sys.argv[0]} <wav파일> <go_log.txt> <python_log.txt> [output.png]")
        print("\n예시:")
        print("  # 1. Go 실행 결과 저장")
        print("  cd golang-practice/src/20250918_vad_filter")
        print("  go run *.go ./sample/arirang_1.mp3 > go_output.txt")
        print("\n  # 2. Python 실행 결과 저장")
        print("  cd python-practice/vad_filter")
        print("  python3 -W ignore vad_test.py ./sample/arirang_1.mp3 > python_output.txt")
        print("\n  # 3. 시각화")
        print("  python3 visualize_vad.py ./sample/arirang_1.wav go_output.txt python_output.txt")
        print("\n  # 4. 특정 구간 상세 보기 (선택)")
        print("  python3 visualize_vad.py ./sample/arirang_1.wav go_output.txt python_output.txt vad_full.png 100 200")
        sys.exit(1)
    
    wav_path = sys.argv[1]
    go_log = sys.argv[2]
    python_log = sys.argv[3]
    output_image = sys.argv[4] if len(sys.argv) > 4 else 'vad_comparison.png'
    
    if not Path(wav_path).exists():
        print(f"❌ WAV 파일을 찾을 수 없습니다: {wav_path}")
        sys.exit(1)
    
    if not Path(go_log).exists():
        print(f"❌ Go 로그 파일을 찾을 수 없습니다: {go_log}")
        sys.exit(1)
    
    if not Path(python_log).exists():
        print(f"❌ Python 로그 파일을 찾을 수 없습니다: {python_log}")
        sys.exit(1)
    
    # 전체 비교
    visualize_vad_comparison(wav_path, go_log, python_log, output_image)
    
    # 특정 구간 상세 비교 (선택)
    if len(sys.argv) >= 7:
        start_time = float(sys.argv[5])
        end_time = float(sys.argv[6])
        detail_image = output_image.replace('.png', '_detail.png')
        visualize_vad_detail(wav_path, go_log, python_log, start_time, end_time, detail_image)
    
    print("\n✅ 모든 시각화 완료!")
    print(f"이미지 파일을 확인하세요: {output_image}")


if __name__ == '__main__':
    main()
