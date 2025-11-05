# asr_backend.py
import os
HAS_NEMO = False
ASRModel = None

try:
    # 지연 임포트: 서버(리눅스+CUDA)에서만 성공
    from nemo.collections.asr.models import ASRModel  # type: ignore
    HAS_NEMO = True
except Exception as e:
    # 로컬 맥에선 여기로 떨어져도 OK (개발/테스트용 폴백)
    print(f"[warn] NeMo not available locally: {e}")

def load_model():
    if not HAS_NEMO:
        raise RuntimeError("NeMo/ASRModel unavailable on this machine")
    model = ASRModel.from_pretrained(model_name="nvidia/canary-1b-v2").eval().to("cuda")
    return model
