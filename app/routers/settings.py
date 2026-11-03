from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from .. import llm
from ..database import get_db
from ..schemas import LLMSettings, LLMSettingsOut, TestResult

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return key[:2] + "****"
    return key[:4] + "****" + key[-4:]


@router.get("/llm", response_model=LLMSettingsOut)
def get_llm_settings():
    cfg = llm.get_llm_config()
    return {
        "enabled": llm.is_enabled(),
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "api_key_masked": _mask(cfg["api_key"]),
    }


@router.put("/llm", response_model=LLMSettingsOut)
def update_llm_settings(body: LLMSettings):
    llm.save_config(body.base_url, body.api_key, body.model)
    return get_llm_settings()


@router.post("/llm/test", response_model=TestResult)
def test_llm():
    if not llm.is_enabled():
        return {"ok": False, "message": "LLM 未配置完整（base_url / api_key / model 需全部填写）"}
    try:
        reply = llm.test_connection()
        return {"ok": True, "message": f"连接成功，模型返回：{reply[:50]}"}
    except Exception as e:
        return {"ok": False, "message": f"连接失败：{type(e).__name__}: {e}"}
