from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from pydantic import BaseModel
import random
import string
from typing import Optional

app = FastAPI()

request_status = {}

@app.post("/stt/main")
async def stt_main(
        file: UploadFile = File(...),
        content_id: str = Form(...),
        rid: str = Form(...),
        job_id: str = Form(...),
        cpk: str = Form(...)
):
    # 4글자 랜덤 req_uid 생성
    req_uid = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

    # 상태 초기화 (pending으로 시작)
    request_status[req_uid] = {
        "status": "pending",
        "created_at": 0,
        "content_id": content_id,
        "job_id": job_id,
        "cpk": cpk
    }

    print(f"✅ Created req_uid: {req_uid} | content_id: {content_id} | job_id: {job_id} | cpk: {cpk} | file: {file.filename}")

    return {
        "req_uid": req_uid,
        "success": True,
    }

@app.post("/stt/progress/{req_uid}/{content_id}")
async def stt_progress(
        req_uid: str,
        content_id: str
):
    if req_uid not in request_status:
        return {
            "status": "pending",
            "content_id": content_id,
            "req_uid": req_uid,
            "overall_progress": 0
        } # 다른 필드 많은데 어차피 이것만 쓸거라 mock 서버는 이것만 리턴

    status_info = request_status[req_uid]
    status_info["created_at"] += 1

    if status_info["created_at"] >= 3:
        # 30% 확률로 completed
        if random.random() < 0.3:
            status_info["status"] = "completed"
            print(f"🎉 {req_uid} -> completed")

    return {
        "status": status_info["status"],
        "req_uid": req_uid,
        "overall_progress": min(status_info["created_at"] * 10, 100),
        "content_id": content_id,
    }

@app.get("/health")
async def health():
    return {"status": "ok"}

# mock server : fast api
if __name__ == "__main__":
    print("\nFast API mock server create")

    import uvicorn
    uvicorn.run(app, host="localhost", port=8000)