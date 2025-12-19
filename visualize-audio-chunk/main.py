import numpy as np
import matplotlib.pyplot as plt
import librosa
import librosa.display
from pathlib import Path

def visualize_chunk_boundaries(audio_path, chunks_info_path, output_dir,
                               context_sec=5.0):
    """
    청크 경계 부분을 확대해서 시각화

    Args:
        audio_path: 오디오 파일 경로
        chunks_info_path: 청크 정보 파일 경로
        output_dir: 출력 디렉토리
        context_sec: 경계 앞뒤로 보여줄 시간 (초)
    """
    # 오디오 로드
    y, sr = librosa.load(audio_path, sr=16000)

    # 청크 정보 파싱
    chunks = parse_chunks_info(chunks_info_path)

    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)

    # 각 청크 경계마다 시각화
    for i in range(len(chunks) - 1):
        current_chunk = chunks[i]
        next_chunk = chunks[i + 1]

        # 경계 시점 (현재 청크 끝 = 다음 청크 시작 근처)
        boundary_time = current_chunk['end']

        # 확대할 구간 계산
        start_time = max(0, boundary_time - context_sec)
        end_time = min(len(y) / sr, boundary_time + context_sec)

        # 해당 구간의 오디오 추출
        start_sample = int(start_time * sr)
        end_sample = int(end_time * sr)
        segment_audio = y[start_sample:end_sample]
        segment_duration = len(segment_audio) / sr
        segment_time = np.linspace(start_time, end_time, len(segment_audio))

        # 시각화
        fig, axes = plt.subplots(3, 1, figsize=(16, 10))

        # 1. 파형
        axes[0].plot(segment_time, segment_audio, linewidth=0.8, alpha=0.8, color='blue')
        axes[0].set_ylabel('Amplitude', fontsize=11)
        axes[0].set_title(
            f'Boundary between Chunk {i} and Chunk {i+1} - Waveform\n'
            f'Showing {context_sec}s before and after boundary at {format_time(boundary_time)}',
            fontsize=13, fontweight='bold'
        )
        axes[0].grid(True, alpha=0.3)
        axes[0].set_xlim([start_time, end_time])

        # 경계선 표시
        axes[0].axvline(boundary_time, color='red', linestyle='--',
                        linewidth=2.5, alpha=0.8, label='Chunk Boundary')

        # 현재 청크 영역 표시
        axes[0].axvspan(start_time, current_chunk['end'],
                        alpha=0.15, color='orange', label=f'Chunk {i} end')

        # 다음 청크 영역 표시
        axes[0].axvspan(next_chunk['start'], end_time,
                        alpha=0.15, color='purple', label=f'Chunk {i+1} start')

        # VAD 세그먼트 표시 (현재 청크)
        for seg in current_chunk['segments']:
            if seg['end'] >= start_time and seg['start'] <= end_time:
                seg_start = max(seg['start'], start_time)
                seg_end = min(seg['end'], end_time)
                axes[0].axvspan(seg_start, seg_end,
                                alpha=0.3, color='green',
                                linewidth=0)

        # VAD 세그먼트 표시 (다음 청크)
        for seg in next_chunk['segments']:
            if seg['end'] >= start_time and seg['start'] <= end_time:
                seg_start = max(seg['start'], start_time)
                seg_end = min(seg['end'], end_time)
                axes[0].axvspan(seg_start, seg_end,
                                alpha=0.3, color='green',
                                linewidth=0)

        # 초록색 패치를 범례에 추가
        from matplotlib.patches import Patch
        legend_elements = axes[0].get_legend_handles_labels()
        speech_patch = Patch(facecolor='green', alpha=0.3, label='Speech (VAD)')
        axes[0].legend(handles=legend_elements[0] + [speech_patch],
                       loc='upper right', fontsize=10)

        # 2. RMS Energy
        frame_length = 2048
        hop_length = 512

        # 해당 구간만 RMS 계산
        rms = librosa.feature.rms(y=segment_audio, frame_length=frame_length,
                                  hop_length=hop_length)[0]
        rms_time = np.linspace(start_time, end_time, len(rms))

        axes[1].plot(rms_time, rms, linewidth=1.5, color='blue', alpha=0.8)
        axes[1].set_ylabel('RMS Energy', fontsize=11)
        axes[1].set_title('Audio Energy (RMS)', fontsize=12, fontweight='bold')
        axes[1].grid(True, alpha=0.3)
        axes[1].set_xlim([start_time, end_time])

        # 경계선
        axes[1].axvline(boundary_time, color='red', linestyle='--',
                        linewidth=2.5, alpha=0.8)

        # VAD 세그먼트 표시
        for seg in current_chunk['segments'] + next_chunk['segments']:
            if seg['end'] >= start_time and seg['start'] <= end_time:
                seg_start = max(seg['start'], start_time)
                seg_end = min(seg['end'], end_time)
                axes[1].axvspan(seg_start, seg_end, alpha=0.2, color='green')

        # 3. 스펙트로그램
        D = librosa.amplitude_to_db(
            np.abs(librosa.stft(segment_audio)),
            ref=np.max
        )
        img = librosa.display.specshow(D, sr=sr, x_axis='time', y_axis='hz',
                                       ax=axes[2], cmap='viridis')
        axes[2].set_title('Spectrogram', fontsize=12, fontweight='bold')

        # x축 시간 조정
        axes[2].set_xlim([0, segment_duration])

        # 실제 시간으로 x축 레이블 변경
        xticks = axes[2].get_xticks()
        xticklabels = [f'{start_time + x:.1f}' for x in xticks]
        axes[2].set_xticklabels(xticklabels)

        fig.colorbar(img, ax=axes[2], format='%+2.0f dB')

        # 경계선 (스펙트로그램 상의 상대 위치)
        boundary_relative = boundary_time - start_time
        axes[2].axvline(boundary_relative, color='red', linestyle='--',
                        linewidth=2.5, alpha=0.8)

        # VAD 세그먼트 표시
        for seg in current_chunk['segments'] + next_chunk['segments']:
            if seg['end'] >= start_time and seg['start'] <= end_time:
                seg_start_rel = max(seg['start'] - start_time, 0)
                seg_end_rel = min(seg['end'] - start_time, segment_duration)
                axes[2].axvspan(seg_start_rel, seg_end_rel,
                                alpha=0.2, color='white')

        axes[2].set_xlabel('Time (seconds)', fontsize=11)

        plt.tight_layout()

        # 저장
        output_path = output_dir / f'boundary_chunk{i}_to_chunk{i+1}.png'
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"✓ Boundary visualization saved: {output_path}")
        plt.close()

    # 각 청크의 시작과 끝 부분도 확대해서 보기
    visualize_chunk_edges(y, sr, chunks, output_dir, context_sec=3.0)

def visualize_chunk_edges(y, sr, chunks, output_dir, context_sec=3.0):
    """
    각 청크의 시작 부분과 끝 부분을 확대해서 시각화
    """
    output_dir = Path(output_dir)

    for chunk_idx, chunk in enumerate(chunks):
        # 청크 시작 부분
        start_time = chunk['start']
        view_start = max(0, start_time - context_sec * 0.5)
        view_end = min(len(y) / sr, start_time + context_sec * 1.5)

        visualize_edge_detail(y, sr, chunk, chunk_idx,
                              view_start, view_end, start_time,
                              'START', output_dir)

        # 청크 끝 부분
        end_time = chunk['end']
        view_start = max(0, end_time - context_sec * 1.5)
        view_end = min(len(y) / sr, end_time + context_sec * 0.5)

        visualize_edge_detail(y, sr, chunk, chunk_idx,
                              view_start, view_end, end_time,
                              'END', output_dir)

def visualize_edge_detail(y, sr, chunk, chunk_idx, view_start, view_end,
                          marker_time, edge_type, output_dir):
    """청크의 시작 또는 끝 부분 상세 시각화"""

    start_sample = int(view_start * sr)
    end_sample = int(view_end * sr)
    segment_audio = y[start_sample:end_sample]
    segment_duration = len(segment_audio) / sr
    segment_time = np.linspace(view_start, view_end, len(segment_audio))

    fig, axes = plt.subplots(2, 1, figsize=(14, 8))

    # 파형
    axes[0].plot(segment_time, segment_audio, linewidth=1, alpha=0.8, color='blue')
    axes[0].set_ylabel('Amplitude', fontsize=11)
    axes[0].set_title(
        f'Chunk {chunk_idx} - {edge_type} Detail\n'
        f'{edge_type} at {format_time(marker_time)}',
        fontsize=13, fontweight='bold'
    )
    axes[0].grid(True, alpha=0.3)
    axes[0].set_xlim([view_start, view_end])

    # 청크 경계 표시
    axes[0].axvline(marker_time, color='red', linestyle='--',
                    linewidth=2.5, alpha=0.8, label=f'Chunk {edge_type}')

    # VAD 세그먼트 표시
    for seg in chunk['segments']:
        if seg['end'] >= view_start and seg['start'] <= view_end:
            seg_start = max(seg['start'], view_start)
            seg_end = min(seg['end'], view_end)
            axes[0].axvspan(seg_start, seg_end,
                            alpha=0.3, color='green', label='Speech')

    # 범례 중복 제거
    handles, labels = axes[0].get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    axes[0].legend(by_label.values(), by_label.keys(), loc='upper right')

    # RMS Energy
    rms = librosa.feature.rms(y=segment_audio, frame_length=2048,
                              hop_length=512)[0]
    rms_time = np.linspace(view_start, view_end, len(rms))

    axes[1].plot(rms_time, rms, linewidth=1.5, color='blue', alpha=0.8)
    axes[1].set_ylabel('RMS Energy', fontsize=11)
    axes[1].set_xlabel('Time (seconds)', fontsize=11)
    axes[1].set_title('Audio Energy', fontsize=12, fontweight='bold')
    axes[1].grid(True, alpha=0.3)
    axes[1].set_xlim([view_start, view_end])

    axes[1].axvline(marker_time, color='red', linestyle='--',
                    linewidth=2.5, alpha=0.8)

    for seg in chunk['segments']:
        if seg['end'] >= view_start and seg['start'] <= view_end:
            seg_start = max(seg['start'], view_start)
            seg_end = min(seg['end'], view_end)
            axes[1].axvspan(seg_start, seg_end, alpha=0.2, color='green')

    plt.tight_layout()

    output_path = output_dir / f'chunk{chunk_idx:04d}_{edge_type.lower()}_detail.png'
    plt.savefig(output_path, dpi=120, bbox_inches='tight')
    print(f"✓ Chunk {chunk_idx} {edge_type} detail saved: {output_path}")
    plt.close()

def parse_chunks_info(chunks_info_path):
    """chunks_info.txt 파일 파싱"""
    chunks = []
    current_chunk = None

    with open(chunks_info_path, 'r') as f:
        for line in f:
            line = line.strip()

            if line.startswith('Chunk #'):
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = {'segments': []}

            elif 'Time Range:' in line:
                parts = line.split(':')[1].strip().replace('s', '').split('-')
                current_chunk['start'] = float(parts[0])
                current_chunk['end'] = float(parts[1])

            elif line.startswith('[') and current_chunk:
                parts = line.split(']')[1].strip().split('-')
                start = float(parts[0].replace('s', '').strip())
                end = float(parts[1].split('(')[0].replace('s', '').strip())
                current_chunk['segments'].append({'start': start, 'end': end})

    if current_chunk:
        chunks.append(current_chunk)

    return chunks

def format_time(seconds):
    """초를 분:초 형식으로 변환"""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{mins:02d}:{secs:02d}.{ms:03d}"

# 사용 예시
if __name__ == "__main__":
    audio_path = "sample/e3_filtered.wav"
    chunks_info_path = "sample/chunks/chunks_info.txt"
    output_dir = "sample/chunks/boundary_viz"

    # 청크 경계 부분 확대 (앞뒤 5초씩)
    visualize_chunk_boundaries(audio_path, chunks_info_path, output_dir,
                               context_sec=5.0)

    print("\n✓ All boundary visualizations completed!")