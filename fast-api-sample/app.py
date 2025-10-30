# app.py
# Minimal FastAPI wrapper around NVIDIA Canary-1B-v2 (NeMo)
# - POST /v1/audio/transcriptions : file upload → JSON (and optional SRT)
# - GET /health

from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse

app = FastAPI(title="ASR REST stub")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/v1/audio/transcriptions")
async def transcriptions(request: Request, file: Optional[UploadFile] = File(None, description="audio file")):
    headers: Dict[str, str] = dict(request.headers)
    content_type = headers.get("content-type", "")

    # check : echo
    resp: Dict[str, Any] = {
        "headers": headers,
        "content_type": content_type,
        "parsed": {},
    }

    if "multipart/form-data" in content_type:
        file_info = None
        if file is not None:
            # ⚠️ 주의: 큰 파일이면 메모리 사용 증가. 실제 서비스에선 스트리밍/임시파일 사용 추천
            content = await file.read()
            file_info = {
                "filename": file.filename,
                "content_type": file.content_type,
                "size_bytes": len(content),
            }
        resp["parsed"] = {
            "file": file_info,
        }
        return JSONResponse(resp)

    raw = await request.body()
    resp["parsed"] = {
        "raw_body_size_bytes": len(raw),
        "note": "Unhandled content-type; just echoing size.",
    }
    return JSONResponse(resp)