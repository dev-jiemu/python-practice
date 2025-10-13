# Python VAD Test

🚀 기존에 Go 언어에서 개발한 VAD Filter를 같은 옵션으로 Python 에서 구현했을때 차이 분석하기

## Install

### 1. 필요한 패키지 설치
```bash
python3 -m pip install -r requirements.txt
```

### 2. FFmpeg 설치 확인
```bash
ffmpeg -version
```

FFmpeg가 없다면 설치:
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg

# Windows (Chocolatey)
choco install ffmpeg
```

## 사용 방법

### 기본 사용
```bash
python3 -W ignore vad_test.py ../sample/audio.mp3
```

### 출력 예시
```
==================================================
Python VAD 필터 테스트
==================================================
입력 파일: ../sample/audio.mp3

오디오 추출 중: ../sample/audio.mp3
추출된 오디오 파일 크기: 2.45 MB
결과 파일: ../sample/audio.wav
⏱️  오디오 추출 시간(mp4 to wav): 0.23초

==================================================
VAD 필터링 시작
==================================================
Silero VAD 모델 로드 중...
오디오 파일 로드 중: ../sample/audio.wav
샘플레이트: 16000 Hz
채널 수: 1 (mono)
총 길이: 153.92초
🔍 PCM 데이터 범위: min=-0.145020, max=0.145020
탐지된 음성 구간: 45개
병합 후 음성 구간: 12개

음성 구간 1: 2.50s ~ 8.30s (5.80s)
음성 구간 2: 10.20s ~ 15.40s (5.20s)
...

📊 처리 결과:
전체 길이: 153.92초 (유지됨)
음성 구간: 89.30초 (58.0%)
긴 무음 제거: 32.50초 (21.1%)
짧은 무음 유지: 32.12초

✅ 처리 완료!
출력 파일: ../sample/audio_vad_filtered.wav

오디오 변환 중: WAV -> WebM
추출된 오디오 파일 크기: 0.23 MB
결과 파일: ../sample/audio_vad_filtered_extracted.webm

==================================================
📊 Results
==================================================
오디오 추출(mp4 to wav):        0.23초 ( 12.5%)
VAD 필터링:                    1.34초 ( 72.8%)
오디오 변환(wav to webm):       0.27초 ( 14.7%)
==================================================
전체 실행 시간:                  1.84초 (100.0%)

✅ 모든 처리 완료!
📁 최종 결과 파일: ../sample/audio_vad_filtered_extracted.webm
```

## Go 버전과 비교

### 비교 방법
```bash
# 1. Go 버전 실행
cd ..
go run *.go sample/audio.mp3

# 2. Python 버전 실행
python3 vad_test.py ../sample/audio.mp3

# 3. 결과 비교
# - 음성 구간 개수 비교
# - 각 구간의 시작/종료 시간 비교 (±50ms 이내면 정상)
# - 전체 처리 시간 비교
python3 compare_results.py ./compare/golang_output.txt ./compare/python_output.txt result.png

# 4. 시각적으로 비교해보고 싶으면
python3 visualize_vad.py ./sample/audio.wav ./compare/golang_output.txt ./compare/python_output.txt result.png
```


## Go 에서 커맨드로 호출하기 위한 단일 스크립트
### 사용방법
```shell
# JSON 경로를 직접 지정
python make_filter_cli.py \
  --in input.wav \
  --out-audio output_vad.wav \
  --out-segments output_vad.json

# JSON 경로 생략 시: out-audio의 스템 + .json 으로 저장
python make_filter_cli.py \
  --in input.wav \
  --out-audio ./out/filtered.wav
```

### 빌드 방법
```shell
pip install pyinstaller
pyinstaller --onefile --name vad_cli \
  --add-data silero_vad.onnx:. \
  --hidden-import torch --hidden-import torchaudio \
  vad_cli.py
# 결과: dist/vad_cli (linux/mac), dist/vad_cli.exe (windows)
```
* 이후, 해당 파일을 Dockerfile 에서 도커 이미지 빌드할때 같이 빌드

## 참고

### ONNX Runtime 에러
```bash
# CPU 버전으로 재설치
pip uninstall onnxruntime onnxruntime-gpu
pip install onnxruntime
```

### Torch/Torchaudio 에러
```bash
# 최신 버전으로 재설치
pip install --upgrade torch torchaudio
```

### FFmpeg 에러
```bash
# FFmpeg 경로 확인
which ffmpeg

# 환경변수에 FFmpeg 추가 (필요시)
export PATH="/usr/local/bin:$PATH"
```

## 참고
- Silero VAD: https://github.com/snakers4/silero-vad
- PyTorch: https://pytorch.org/
- Torchaudio: https://pytorch.org/audio/
