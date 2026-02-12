from fastapi import FastAPI, File, UploadFile, Form
from typing import List, Optional
import random

app = FastAPI()

request_status = {}

@app.post("/stt/main")
async def stt_main(
        file: UploadFile = File(...),
        usr_api_token: str = Form(...),
        filename: str = Form(...),
        content_id: str = Form(...),
        do_after_process: str = Form(...),
        hotwords: Optional[List[str]] = Form(None)  # 배열은 Optional
):

    # 디버깅 추가
    print(f"Received - file: {file.filename}, content_id: {content_id}")

    # 4글자 랜덤 req_uid 생성
    req_uid = random.randint(1, 9999)

    # 상태 초기화
    request_status[str(req_uid)] = {
        "status": "pending",
        "created_at": 0,
        "content_id": content_id,
        "filename": filename
    }

    print(f"✅ Created req_uid: {req_uid} | content_id: {content_id} | filename: {filename} | file: {file.filename}")

    return {
        "req_uid": req_uid,  # 숫자로 반환
    }

@app.get("/stt/progress/{req_uid}/{content_id}")
async def stt_progress(
        req_uid: str,
        content_id: str
):
    print(f"📊 req_uid: {req_uid}, content_id: {content_id}")

    if req_uid not in request_status:
        return {
            "status": "pending",
            "content_id": content_id,
            "req_uid": int(req_uid),
            "overall_progress": 0
        } # 다른 필드 많은데 어차피 이것만 쓸거라 mock 서버는 이것만 리턴

    status_info = request_status[req_uid]
    status_info["created_at"] += 1

    if status_info["created_at"] >= 2:
        # 70% 확률로 completed
        if random.random() < 0.7:
            status_info["status"] = "completed"
            print(f"🎉 {req_uid} -> completed")

    return {
        "status": status_info["status"],
        "req_uid": int(req_uid),
        "overall_progress": min(status_info["created_at"] * 10, 100),
        "content_id": content_id,
    }

@app.get("/health")
async def health():
    return {"status": "ok"}

# 빌드 할때 [pyinstaller --onefile --console mock_server.py]
if __name__ == "__main__":
    print("Fast API mock server create :)")

    import uvicorn
    uvicorn.run(app, host="localhost", port=8000)