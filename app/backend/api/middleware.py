"""HTTP validation, desktop process-key boundary and CORS registration."""
import secrets
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


async def request_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {
            "field": ".".join(str(part) for part in error["loc"] if part not in {"body", "query", "path"}),
            "code": str(error["type"]),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "request_validation_failed",
                "message": "输入数据无效，请检查字段格式和范围",
                "errors": errors,
            }
        },
    )


async def require_process_key(request: Request, call_next):
    # 进程密钥用于证明请求属于本次由 Tauri 启动的 sidecar；
    # Bearer 身份认证仍是彼此独立的用户级门禁。
    process_key = request.app.state.runtime.process_key
    if process_key and request.method != "OPTIONS":
        supplied = request.headers.get("X-GeoSpectrum-Process-Key", "")
        if not secrets.compare_digest(supplied, process_key):
            return JSONResponse(status_code=403, content={"detail": {"code": "PROCESS_KEY_REQUIRED", "message": "本地进程密钥无效"}})
    return await call_next(request)


def register_middleware(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, request_validation_error)
    app.middleware("http")(require_process_key)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "tauri://localhost",
            "http://tauri.localhost",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-Correlation-ID", "X-GeoSpectrum-Process-Key"],
        expose_headers=["X-Page-Count", "X-Field-Count", "X-Method-Version", "X-Content-SHA256", "Content-Disposition"],
    )
