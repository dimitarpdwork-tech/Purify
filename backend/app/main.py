from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text

from app.api.routes import api
from app.core.config import get_settings
from app.core.db import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
settings = get_settings()



@asynccontextmanager
async def lifespan(_app: FastAPI):
    bootstrap_admin()
    yield


app = FastAPI(title="Purify Publisher Intelligence", version="0.4.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(api)


def bootstrap_admin() -> None:
    if settings.secret_key == "change-me" and settings.environment == "production":
        raise RuntimeError("SECRET_KEY must be set in production")
    if not (settings.bootstrap_admin_email and settings.bootstrap_admin_password):
        return
    from app.core.security import hash_password
    from app.models import User

    db = SessionLocal()
    try:
        if not db.scalar(select(User.id).limit(1)):
            db.add(User(email=settings.bootstrap_admin_email.lower(), password_hash=hash_password(settings.bootstrap_admin_password), role="admin"))
            db.commit()
    finally:
        db.close()


@app.get("/api/health")
def health() -> dict:
    out = {"api": "ok"}
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        out["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        out["database"] = f"error: {exc}"
    finally:
        db.close()
    try:
        import redis

        redis.Redis.from_url(settings.redis_url, socket_timeout=2).ping()
        out["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        out["redis"] = f"error: {exc}"
    return out
