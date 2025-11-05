# main.py
# Minimal FastAPI wrapper around NVIDIA Canary-1B-v2 (NeMo)
# - POST /v1/audio/transcriptions : file upload → JSON (and optional SRT)
# - GET /health
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from .asr_backend import load_model, HAS_NEMO
from .schemas import TranscribeResponse, Segment

app = FastAPI(title="Canary ASR API")

model = None
@app.on_event("startup")
def _startup():
    global model
    if HAS_NEMO:
        model = load_model()  # 서버에서만 실제 로드
    else:
        model = None

@app.get("/health")
def health():
    return {"status": "ok", "nemo": HAS_NEMO}

@app.get("/v1/audio/transcriptions")
async def transcriptions(
        file: UploadFile = File(...),
        source_lang: str = Form("en"),
        target_lang: str = Form("en"),
        with_timestamps: bool = Form(True),
):
    if not HAS_NEMO:
        # 로컬 개발 환경에선 501로 응답(엔드포인트/스키마는 검증 가능)
        raise HTTPException(status_code=501, detail="ASR disabled on this machine")

