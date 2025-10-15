# VAD Filter Comparison Tool

Go 언어와 Python으로 각각 구현된 Silero VAD (Voice Activity Detection) 필터의 결과를 시각적으로 비교하는 도구

## 🎯 주요 기능

### 1. 시각화 차트 (5개)
- **Original Audio Waveform**: 원본 오디오 파형
- **Go VAD Filtered**: Go 라이브러리로 필터링된 파형
- **Python VAD Filtered**: Python으로 필터링된 파형
- **Voice/Silence Segments Comparison**: 음성/무음 구간 비교 (상단: Go, 하단: Python)
  - 🔴 빨간색: Go만 음성으로 판단 (Python이 더 많이 자름)
  - 🔵 파란색: Python만 음성으로 판단 (Go가 더 많이 자름)
- **Amplitude Level Comparison**: RMS 진폭 레벨 비교

### 2. 통계 분석
```
📊 필터링 비율:
  - 각 필터가 음성으로 남긴 비율
  - 무음 처리한 비율

🔍 차이 분석:
  - 총 차이 프레임 수와 비율
  - Go/Python 간 차이 구간 상세 분석
  - 어느 필터가 더 공격적으로 필터링하는지 판단
```

## 🚀 사용 방법

```python
python main.py
```

### 3. 코드 내 경로 수정
```python
if __name__ == "__main__":
    # 파일 경로 설정
    original_wav = ""
    go_filtered_wav = ""
    python_filtered_wav = ""
    
    # 비교 실행
    stats = plot_vad_comparison(
        original_wav,
        go_filtered_wav,
        python_filtered_wav,
        save_path="vad_comparison.png"
    )
```

## 📦 의존성

```bash
pip install numpy matplotlib librosa scipy
```

## 📊 출력 예시

```
============================================================
VAD Filter Comparison Results
============================================================
Total duration: 25.50 seconds

📊 필터링 비율:
  Go Filter:
    - 음성으로 남김: 1250 frames (85.3%)
    - 무음 처리함: 215 frames (14.7%)
  Python Filter:
    - 음성으로 남김: 1100 frames (75.0%)
    - 무음 처리함: 365 frames (25.0%)

🔍 차이 분석:
  - 총 차이 프레임: 180 frames (12.3%)
  - 🔴 Go만 음성 (Python이 자름): 160 frames (10.91%)
  - 🔵 Python만 음성 (Go가 자름): 20 frames (1.36%)

📈 차이 구간 중:
  - Go만 음성: 88.9% (Python이 160 프레임 더 자름)
  - Python만 음성: 11.1% (Go가 20 프레임 더 자름)

💡 결론:
  ✅ Python이 Go보다 훨씬 더 공격적으로 필터링 (약 8.0배)
     → Python이 잡음 제거에 더 적극적
============================================================
```

## 🎨 시각화 특징

- **한글 폰트 지원**: macOS의 AppleGothic 사용
- **고해상도 저장**: 300 DPI PNG 파일
- **컬러 코딩**:
  - 회색: 원본
  - 빨강: Go 필터
  - 청록: Python 필터
- **차이 하이라이트**: 불일치 구간을 진한 색으로 강조

## 🔍 비교 목적

1. **세그먼트 길이**: Go가 오디오를 너무 잘게 쪼개는가?
2. **Whisper 환각 가능성**: 짧은 세그먼트가 많으면 환각 현상 증가
3. **최적 파라미터**: MinSilenceDurationMs 값 (100ms, 500ms, 30000ms 등) 비교
4. **구현 선택**: Python subprocess를 호출할지, Go 라이브러리를 사용할지 결정

## ⚠️ 주의사항

- **이미 필터링된 파일**을 비교 (실시간 VAD 적용이 아님)
- 샘플링 레이트가 다르면 경고 메시지 출력
- 오디오 길이가 다르면 자동으로 패딩 처리
- GUI 없이 파일로만 저장 (`matplotlib.use('Agg')`)

## 📌 관련 이슈

- Go 라이브러리: `github.com/streamer45/silero-vad-go/speech`
- Python 라이브러리: `torch.hub.load("snakers4/silero-vad")`
- Whisper API 환각 현상과 VAD 세그먼트 길이의 상관관계
