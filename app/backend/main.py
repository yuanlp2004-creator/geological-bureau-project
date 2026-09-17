"""GeoSpectrum 应用入口：装配运行容器、生命周期、中间件与 API。

接口位于 api/，业务服务位于 modules/，请求模型位于 schemas/。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__
from .config import AppConfig
from .schemas.system import RuntimeEventCreate

from .runtime import Runtime
from .api import register_api
from .api.middleware import register_middleware


@asynccontextmanager
async def lifespan(application: FastAPI):
    runtime = application.state.runtime
    # Preserve initialization before permission synchronization and startup audit.
    runtime.config.ensure_directories()
    runtime.database.initialize()
    runtime.auth_service.synchronize_builtin_permissions()
    runtime.service.append_event(RuntimeEventCreate(category="system", severity="success", message="本地服务已启动"))
    yield
    runtime.service.append_event(RuntimeEventCreate(category="system", severity="info", message="本地服务已停止"))


def create_app(config: AppConfig | None = None, *, runtime: Runtime | None = None) -> FastAPI:
    """Build an isolated application without opening/initializing its database."""
    if config is not None and runtime is not None:
        raise ValueError("provide either config or runtime")
    application = FastAPI(title="GeoSpectrum API", version=__version__, lifespan=lifespan)
    application.state.runtime = runtime if runtime is not None else Runtime(config or AppConfig())
    register_middleware(application)
    register_api(application)
    return application


app = create_app()
