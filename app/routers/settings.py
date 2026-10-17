"""轻量设置接口。业务数据库仍用同步 Session，耗时测试连接单独异步执行。"""

import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import SessionLocal, get_db
from app.models import User, UserModelConfig
from app import model_settings

router = APIRouter(prefix="/settings", tags=["settings"])


class ModelConfigInput(BaseModel):
    base_url: str = Field(min_length=1, max_length=512)
    model_name: str = Field(min_length=1, max_length=200)
    api_key: SecretStr | None = Field(default=None, max_length=4096)


def _resolve(db, user_id, body):
    key = body.api_key.get_secret_value() if body.api_key is not None else None
    return model_settings.resolve_input(db, user_id, body.base_url, body.model_name, key)


@router.get("/model")
def get_model_config(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return model_settings.config_status(db, current.id)


@router.put("/model")
def put_model_config(body: ModelConfigInput, current: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    connection = _resolve(db, current.id, body)
    return model_settings.save_config(db, current.id, connection)


@router.delete("/model")
def delete_model_config(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(UserModelConfig, current.id)
    if row is not None:
        db.delete(row)
        db.commit()
    return model_settings.config_status(db, current.id)


@router.post("/model/test")
async def test_model_config(body: ModelConfigInput, current: User = Depends(get_current_user)):
    def load():
        with SessionLocal() as db:
            return _resolve(db, current.id, body)

    connection = await asyncio.to_thread(load)
    await model_settings.test_connection(connection)
    return {"ok": True, "message": "连接成功（短文本请求；未保存配置）"}
