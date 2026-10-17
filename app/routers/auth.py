from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth import create_token, get_current_user, hash_password, verify_password
from app.database import get_db
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str


class PasswordChange(BaseModel):
    old_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=6, max_length=128)


@router.post("/password")
def change_password(body: PasswordChange, current: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    old_password = body.old_password.get_secret_value()
    new_password = body.new_password.get_secret_value()
    # bcrypt 的上限是 UTF-8 字节数，不是中文字符数，提前检查避免抛 500。
    if len(new_password.encode("utf-8")) > 72:
        raise HTTPException(400, "新密码最多 72 个 UTF-8 字节（中文通常占 3 字节）")
    if not verify_password(old_password, current.password_hash):
        raise HTTPException(400, "原密码不正确")
    if old_password == new_password:
        raise HTTPException(400, "新密码不能与原密码相同")
    # 条件更新防止两个并发改密请求都用同一旧密码成功。
    changed = db.execute(update(User).where(
        User.id == current.id, User.password_hash == current.password_hash,
    ).values(password_hash=hash_password(new_password)))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "密码已发生变化，请重新输入原密码")
    db.commit()
    # 本版不做设备/令牌撤销，已有登录保持有效，后续登录须使用新密码。
    return {"message": "密码已修改；下次登录请使用新密码，已有登录保持有效"}


@router.post("/register", response_model=TokenOut)
def register(body: Credentials, db: Session = Depends(get_db)):
    if len(body.password.encode("utf-8")) > 72:
        raise HTTPException(400, "密码最多 72 个 UTF-8 字节")
    exists = db.execute(
        select(User).where(User.username == body.username)
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在")

    user = User(username=body.username, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    return TokenOut(
        access_token=create_token(user.id),
        user_id=user.id,
        username=user.username,
    )


@router.post("/login", response_model=TokenOut)
def login(body: Credentials, db: Session = Depends(get_db)):
    user = db.execute(
        select(User).where(User.username == body.username)
    ).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )

    return TokenOut(
        access_token=create_token(user.id),
        user_id=user.id,
        username=user.username,
    )


@router.get("/me")
def me(current: User = Depends(get_current_user)):
    return {
        "user_id": current.id,
        "username": current.username,
        "is_admin": current.is_admin,
    }
