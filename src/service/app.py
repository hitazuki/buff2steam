from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field

from src.monitoring.smis_client import SmisClient
from src.monitoring.storage import MonitorStorage
from src.notifications.astrbot import AstrBotNotifier

from .manager import MonitoringManager, ServiceError
from .runtime import ServiceRuntime

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


class RuleCreate(BaseModel):
    umo: str = Field(min_length=3, max_length=500)
    smis_id: int = Field(gt=0)
    rule_type: str = Field(min_length=2, max_length=20)
    threshold: float = Field(gt=0)


class RuleUpdate(BaseModel):
    umo: str = Field(min_length=3, max_length=500)
    threshold: float = Field(gt=0)


class PushTest(BaseModel):
    umo: str = Field(min_length=3, max_length=500)


def ok(data=None) -> dict:
    return {"ok": True, "data": data}


def create_app(
    manager: MonitoringManager | None = None,
    runtime: ServiceRuntime | None = None,
    service_token: str | None = None,
) -> FastAPI:
    token = service_token if service_token is not None else os.getenv("BUFF2STEAM_SERVICE_TOKEN", "")
    if manager is None:
        database = Path(os.getenv("BUFF2STEAM_DATABASE", "./data/monitor.db"))
        notifier = AstrBotNotifier(
            os.getenv("ASTRBOT_BASE_URL", "http://astrbot:6185"),
            os.getenv("ASTRBOT_API_KEY", ""),
            os.getenv("ASTRBOT_MESSAGE_PATH", "/api/v1/im/message"),
            float(os.getenv("ASTRBOT_TIMEOUT_SECONDS", "10")),
        )
        manager = MonitoringManager(
            MonitorStorage(database),
            SmisClient(
                timeout=float(os.getenv("SMIS_TIMEOUT_SECONDS", "15")),
                max_retries=int(os.getenv("SMIS_MAX_RETRIES", "3")),
            ),
            notifier,
            max_items=int(os.getenv("BUFF2STEAM_MAX_ITEMS", "20")),
            quote_cache_seconds=int(os.getenv("BUFF2STEAM_QUOTE_CACHE_SECONDS", "60")),
        )
    if runtime is None:
        runtime = ServiceRuntime(
            manager,
            interval_seconds=int(os.getenv("BUFF2STEAM_INTERVAL_SECONDS", "1800")),
            backup_dir=Path(os.getenv("BUFF2STEAM_BACKUP_DIR", "./data/backups")),
        )

    async def require_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        import secrets

        if not token or credentials is None or not secrets.compare_digest(credentials.credentials, token):
            raise ServiceError(401, "unauthorized", "服务令牌无效")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        runtime.start()
        yield
        runtime.stop()

    app = FastAPI(title="buff2steam service", version="2.0.0", lifespan=lifespan)
    app.state.manager = manager
    app.state.runtime = runtime

    @app.exception_handler(ServiceError)
    async def service_error_handler(_: Request, exc: ServiceError):
        error = {"code": exc.code, "message": exc.message}
        if exc.data is not None:
            error["data"] = exc.data
        return JSONResponse(status_code=exc.status_code, content={"ok": False, "error": error})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "error": {"code": "validation_error", "message": "请求参数无效", "data": exc.errors()},
            },
        )

    @app.get("/healthz")
    async def healthz():
        status = runtime.status()
        return JSONResponse(
            status_code=200 if status.get("running") else 503,
            content=ok(status),
        )

    @app.get("/v1/items", dependencies=[Depends(require_token)])
    async def items():
        return ok(await run_in_threadpool(manager.list_items))

    @app.get("/v1/search", dependencies=[Depends(require_token)])
    async def search_items(
        q: str = Query(min_length=1, max_length=200),
        limit: int = Query(default=10, ge=1, le=20),
    ):
        return ok(await run_in_threadpool(manager.search_items, q, limit))

    @app.get("/v1/quote", dependencies=[Depends(require_token)])
    async def quote_item(q: str = Query(min_length=1, max_length=200)):
        return ok(await run_in_threadpool(manager.quote, q))

    @app.get("/v1/rules", dependencies=[Depends(require_token)])
    async def rules(
        umo: str = Query(min_length=3, max_length=500),
        smis_id: int | None = Query(default=None, gt=0),
    ):
        return ok(await run_in_threadpool(manager.list_rules, umo, smis_id))

    @app.post("/v1/rules", dependencies=[Depends(require_token)])
    async def add_rule(body: RuleCreate):
        return ok(await run_in_threadpool(
            manager.add_rule, body.umo, body.smis_id, body.rule_type, body.threshold
        ))

    @app.patch("/v1/rules/{rule_id}", dependencies=[Depends(require_token)])
    async def update_rule(rule_id: int, body: RuleUpdate):
        return ok(await run_in_threadpool(
            manager.update_rule, body.umo, rule_id, body.threshold
        ))

    @app.delete("/v1/rules/{rule_id}", dependencies=[Depends(require_token)])
    async def remove_rule(rule_id: int, umo: str = Query(min_length=3, max_length=500)):
        await run_in_threadpool(manager.remove_rule, umo, rule_id)
        return ok({"removed": True})

    @app.post("/v1/push/test", dependencies=[Depends(require_token)])
    async def push_test(body: PushTest):
        await run_in_threadpool(manager.test_push, body.umo)
        return ok({"sent": True})

    return app


app = create_app()
