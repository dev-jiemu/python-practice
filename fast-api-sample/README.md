### 설정 및 실행
```shell
pip install fastapi uvicorn
uvicorn app:app --host 0.0.0.0 --port 9000
```



#### 메모 : 환경설정 
```shell
python -m venv .venv && source .venv/bin/activate
pip install --upgrade pip

# PyTorch 먼저 (GPU CUDA 12.1 기준)
pip install 'torch>=2.3,<3' 'torchaudio>=2.3,<3' --index-url https://download.pytorch.org/whl/cu121
# CPU만 쓸 때
# pip install 'torch>=2.3,<3' 'torchaudio>=2.3,<3' --index-url https://download.pytorch.org/whl/cpu

# NeMo ASR만
pip install 'nemo_toolkit[asr]'

# FastAPI 서버 돌릴 거면
pip install fastapi uvicorn ffmpeg-python python-multipart
```