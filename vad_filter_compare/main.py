import numpy as np
import matplotlib
matplotlib.use('Agg')  # GUI 없이 파일만 저장 (warning 방지)
import matplotlib.pyplot as plt
import librosa
import librosa.display
import os
import warnings

# Warning 무시
warnings.filterwarnings('ignore', category=UserWarning)

# 한글 폰트 설정 (macOS)
plt.rcParams['font.family'] = 'AppleGothic'  # macOS 기본 한글 폰트
plt.rcParams['axes.unicode_minus'] = False  # 마이너스 기호 깨짐 방지

SOFT_GATE_GO = 0.01                # Go에서 사용한 softGateAtt 값과 동일하게
EPS_GO = SOFT_GATE_GO * 0.9        # ← 0.9~1.0 배 권장 (예: 0.009)
EPS_PY = 0.001                     # Python은 하드컷이면 그대로 OK

def detect_voice_from_amplitude(audio, sr, silence_threshold=0.001, frame_length=0.02):
    """
    이미 필터링된 오디오에서 무음/음성 구간 감지
    진폭이 거의 0인 구간 = 무음 처리된 구간
    """
    frame_samples = int(sr * frame_length)
    hop_samples = int(sr * 0.01)  # 10ms

    # 각 프레임의 RMS (Root Mean Square) 계산
    rms = np.array([
        np.sqrt(np.mean(audio[i:i+frame_samples]**2))
        for i in range(0, len(audio)-frame_samples, hop_samples)
    ])

    # 무음 여부 판단 (이미 필터링된 결과이므로 낮은 threshold 사용)
    is_voice = rms > silence_threshold

    # 시간으로 변환
    times = np.arange(len(is_voice)) * hop_samples / sr

    return times, is_voice, rms

def find_differences(voice1, voice2):
    """두 VAD 결과의 차이 구간 찾기"""
    min_len = min(len(voice1), len(voice2))
    voice1 = voice1[:min_len]
    voice2 = voice2[:min_len]

    # XOR로 차이 찾기
    diff = np.logical_xor(voice1, voice2)
    return diff

def plot_vad_comparison(original_path, go_filtered_path, python_filtered_path,
                        save_path=None):
    """
    VAD 필터 결과를 비교하는 상세 시각화
    (이미 필터링된 파일들을 직접 비교)

    Parameters:
    - original_path: 원본 WAV 파일 경로
    - go_filtered_path: Go로 처리한 WAV 파일 경로
    - python_filtered_path: Python으로 처리한 WAV 파일 경로
    - save_path: 저장할 경로 (None이면 화면에만 표시)
    """

    # WAV 파일 로드
    print("Loading audio files...")
    original, sr_orig = librosa.load(original_path, sr=None)
    go_filtered, sr_go = librosa.load(go_filtered_path, sr=None)
    python_filtered, sr_py = librosa.load(python_filtered_path, sr=None)

    # 샘플링 레이트 확인
    if not (sr_orig == sr_go == sr_py):
        print(f"Warning: Different sample rates - Original: {sr_orig}, Go: {sr_go}, Python: {sr_py}")
    sr = sr_orig

    # 길이 맞추기
    max_len = max(len(original), len(go_filtered), len(python_filtered))
    original = np.pad(original, (0, max_len - len(original)))
    go_filtered = np.pad(go_filtered, (0, max_len - len(go_filtered)))
    python_filtered = np.pad(python_filtered, (0, max_len - len(python_filtered)))

    # VAD 분석 (필터링된 결과에서 무음/음성 구간 추출)
    print("Analyzing voice activity from filtered files...")

    times_orig, voice_orig, rms_orig = detect_voice_from_amplitude(original, sr, silence_threshold=EPS_PY)
    times_go,   voice_go,   rms_go   = detect_voice_from_amplitude(go_filtered, sr, silence_threshold=EPS_GO)
    times_py,   voice_py,   rms_py   = detect_voice_from_amplitude(python_filtered, sr, silence_threshold=EPS_PY)

    # times_*는 프레임 경계라 길이가 voice_*보다 1 크게 만들어짐. 색칠할 땐 times[i]~times[i+1]라 +1 필요.
    L = min(len(voice_go), len(voice_py), len(times_go) - 1, len(times_py) - 1)
    voice_go = voice_go[:L]
    voice_py = voice_py[:L]
    times_go = times_go[:L + 1]
    times_py = times_py[:L + 1]
    rms_go   = rms_go[:L]   # 아래 RMS 패널도 같은 프레임 수로 맞춤
    rms_py   = rms_py[:L]

    # 차이 계산
    diff_go_py = find_differences(voice_go, voice_py)

    # 차이 세부 분석
    go_only = voice_go & ~voice_py  # Go만 음성으로 판단 (Python이 더 많이 자름)
    py_only = voice_py & ~voice_go  # Python만 음성으로 판단 (Go가 더 많이 자름)

    # 시각화
    fig = plt.figure(figsize=(16, 12))

    # 전체 시간축
    time_axis = np.linspace(0, len(original)/sr, len(original))

    print(f"[len] voice_go={len(voice_go)}, voice_py={len(voice_py)}, times_go={len(times_go)}, times_py={len(times_py)}")
    print(f"[thr] EPS_GO={EPS_GO}, EPS_PY={EPS_PY}")
    print(f"[rms] go min/med/max = {rms_go.min():.5f}/{np.median(rms_go):.5f}/{rms_go.max():.3f}")
    print(f"[rms] py min/med/max = {rms_py.min():.5f}/{np.median(rms_py):.5f}/{rms_py.max():.3f}")

    # 1. 파형 비교
    ax1 = plt.subplot(5, 1, 1)
    plt.plot(time_axis, original, alpha=0.7, linewidth=0.5, label='Original', color='gray')
    plt.ylabel('Amplitude')
    plt.title('Original Audio Waveform', fontsize=12, fontweight='bold')
    plt.xlim(0, time_axis[-1])
    plt.grid(True, alpha=0.3)
    plt.legend(loc='upper right')

    ax2 = plt.subplot(5, 1, 2)
    plt.plot(time_axis, go_filtered, alpha=0.7, linewidth=0.5, label='Go Filtered', color='#FF6B6B')
    plt.ylabel('Amplitude')
    plt.title('Go VAD Filtered', fontsize=12, fontweight='bold')
    plt.xlim(0, time_axis[-1])
    plt.grid(True, alpha=0.3)
    plt.legend(loc='upper right')

    ax3 = plt.subplot(5, 1, 3)
    plt.plot(time_axis, python_filtered, alpha=0.7, linewidth=0.5, label='Python Filtered', color='#4ECDC4')
    plt.ylabel('Amplitude')
    plt.title('Python VAD Filtered', fontsize=12, fontweight='bold')
    plt.xlim(0, time_axis[-1])
    plt.grid(True, alpha=0.3)
    plt.legend(loc='upper right')

    # 2. 음성/무음 구간 비교 (차이 구분 표시)
    ax4 = plt.subplot(5, 1, 4)

    # Go 결과 (상단)
    for i in range(L):
        if voice_go[i]:
            ax4.axvspan(times_go[i], times_go[i+1], ymin=0.5, ymax=1.0,
                        alpha=0.5, color='#FF6B6B', label='Go: Voice' if i == 0 else '')

    # Python 결과 (하단)
    for i in range(L):
        if voice_py[i]:
            ax4.axvspan(times_py[i], times_py[i+1], ymin=0.0, ymax=0.5,
                        alpha=0.5, color='#4ECDC4', label='Python: Voice' if i == 0 else '')

    # 차이 구간 표시
    for i in range(L):
        if go_only[i]:
            ax4.axvspan(times_go[i], times_go[i+1], ymin=0.5, ymax=1.0,
                        alpha=0.9, color='red', edgecolor='darkred', linewidth=0.5)
        if py_only[i]:
            ax4.axvspan(times_py[i], times_py[i+1], ymin=0.0, ymax=0.5,
                        alpha=0.9, color='blue', edgecolor='darkblue', linewidth=0.5)

    plt.ylim(0, 1)
    plt.ylabel('Voice Activity')
    plt.title('Voice/Silence Segments Comparison\n(Top: Go | Bottom: Python | Red: Go만 음성 | Blue: Python만 음성)',
              fontsize=12, fontweight='bold')
    plt.yticks([0.25, 0.75], ['Python', 'Go'])
    plt.xlim(0, time_axis[-1])
    plt.grid(True, alpha=0.3, axis='x')

    # 범례 정리
    handles, labels = ax4.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    plt.legend(by_label.values(), by_label.keys(), loc='upper right')

    # 3. RMS (진폭) 레벨 비교
    ax5 = plt.subplot(5, 1, 5)

    # x축은 프레임 경계 times에서 마지막 요소 제외(길이 L에 맞춤)
    plt.plot(times_go[:-1], rms_go, label='Go Filtered', color='#FF6B6B', linewidth=2, alpha=0.8)
    plt.plot(times_py[:-1], rms_py, label='Python Filtered', color='#4ECDC4', linewidth=2, alpha=0.8)

    # 파일별 임계선
    plt.axhline(y=EPS_GO, color='#FF6B6B', linestyle='--', linewidth=2, label=f'Go Silence Th ({EPS_GO:g})')
    plt.axhline(y=EPS_PY, color='#4ECDC4', linestyle='--', linewidth=2, label=f'Py Silence Th ({EPS_PY:g})')

    plt.ylabel('RMS Amplitude')
    plt.xlabel('Time (seconds)')
    plt.title('Amplitude Level Comparison (거의 0 = 무음 처리됨)', fontsize=12, fontweight='bold')
    plt.xlim(0, time_axis[-1])
    plt.grid(True, alpha=0.3)
    plt.legend(loc='upper right')

    plt.tight_layout()

    # 파일 저장
    if save_path:
        # 절대 경로로 변환
        save_path = os.path.abspath(save_path)
        print(f"\nSaving plot to: {save_path}")
        plt.savefig(save_path, dpi=300, bbox_inches='tight')

        # 저장 확인
        if os.path.exists(save_path):
            file_size = os.path.getsize(save_path) / 1024  # KB
            print(f"✓ File saved successfully! Size: {file_size:.1f} KB")
        else:
            print("✗ File save failed!")

    # 통계 출력
    print("\n" + "="*60)
    print("VAD Filter Comparison Results")
    print("="*60)
    print(f"Total duration: {len(original)/sr:.2f} seconds")

    print(f"\n📊 필터링 비율:")
    print(f"  Go Filter:")
    print(f"    - 음성으로 남김: {np.sum(voice_go)} frames ({np.sum(voice_go)/len(voice_go)*100:.1f}%)")
    print(f"    - 무음 처리함: {np.sum(~voice_go)} frames ({np.sum(~voice_go)/len(voice_go)*100:.1f}%)")
    print(f"  Python Filter:")
    print(f"    - 음성으로 남김: {np.sum(voice_py)} frames ({np.sum(voice_py)/len(voice_py)*100:.1f}%)")
    print(f"    - 무음 처리함: {np.sum(~voice_py)} frames ({np.sum(~voice_py)/len(voice_py)*100:.1f}%)")

    diff_ratio = np.sum(diff_go_py)/len(diff_go_py)*100
    print(f"\n🔍 차이 분석:")
    print(f"  - 총 차이 프레임: {np.sum(diff_go_py)} frames ({diff_ratio:.1f}%)")
    print(f"  - 🔴 Go만 음성 (Python이 자름): {np.sum(go_only)} frames ({np.sum(go_only)/len(go_only)*100:.2f}%)")
    print(f"  - 🔵 Python만 음성 (Go가 자름): {np.sum(py_only)} frames ({np.sum(py_only)/len(py_only)*100:.2f}%)")

    # 비율 계산
    if np.sum(diff_go_py) > 0:
        go_only_ratio = np.sum(go_only) / np.sum(diff_go_py) * 100
        py_only_ratio = np.sum(py_only) / np.sum(diff_go_py) * 100
        print(f"\n📈 차이 구간 중:")
        print(f"  - Go만 음성: {go_only_ratio:.1f}% (Python이 {np.sum(go_only)} 프레임 더 자름)")
        print(f"  - Python만 음성: {py_only_ratio:.1f}% (Go가 {np.sum(py_only)} 프레임 더 자름)")

        print(f"\n💡 결론:")
        if np.sum(go_only) > np.sum(py_only) * 3:
            print(f"  ✅ Python이 Go보다 훨씬 더 공격적으로 필터링 (약 {go_only_ratio/py_only_ratio:.1f}배)")
            print(f"     → Python이 잡음 제거에 더 적극적")
        elif np.sum(py_only) > np.sum(go_only) * 3:
            print(f"  ✅ Go가 Python보다 훨씬 더 공격적으로 필터링 (약 {py_only_ratio/go_only_ratio:.1f}배)")
            print(f"     → Go가 잡음 제거에 더 적극적")
        else:
            print(f"  ✅ 두 필터가 비슷한 수준으로 작동")
            print(f"     → 미세한 경계선 차이만 존재")

    print("="*60)

    print("\n✅ 비교 완료! 저장된 이미지를 확인해보세요.")

    # 메모리 정리
    plt.close()

    return {
        'go_voice_ratio': np.sum(voice_go)/len(voice_go),
        'python_voice_ratio': np.sum(voice_py)/len(voice_py),
        'difference_ratio': np.sum(diff_go_py)/len(diff_go_py),
        'go_only_voice': np.sum(go_only),
        'python_only_voice': np.sum(py_only)
    }

# 사용 예시
if __name__ == "__main__":
    # 파일 경로 설정
    original_wav = "./sample/arirang_1_original.wav"
    go_filtered_wav = "./sample/arirang_1_vad_filtered_optimize.wav"
    python_filtered_wav = "./sample/arirang_1_vad_filtered_python.wav"

    # 비교 실행 (필터링된 파일을 직접 비교)
    stats = plot_vad_comparison(
        original_wav,
        go_filtered_wav,
        python_filtered_wav,
        save_path="vad_comparison.png"
    )