# 数据库与 API 装配导读

## 1. 为什么先读组合根

后端业务已拆到 `modules/*.py`。R3 已完成全部 API 与模型分类；R6 已将基线、历史迁移和默认数据迁入 migrations/，db.py 保留连接、事务和调度。跨层排查时先掌握这些入口：

- [`main.py`](../../app/backend/main.py)：FastAPI 应用工厂与生命周期（44 行）；业务路由在 api/，WebSocket 在 api/events.py。
- [`runtime.py`](../../app/backend/runtime.py)：每个应用独立的数据库、认证、业务服务及事件订阅状态。
- [`api/system.py`](../../app/backend/api/system.py)：健康、关于、诊断、设置和运行消息接口。
- [`api/dependencies.py`](../../app/backend/api/dependencies.py)：请求认证与权限检查，从当前应用获取 runtime。
- [`api/middleware.py`](../../app/backend/api/middleware.py)：进程密钥、CORS 和校验错误处理。
- [`schemas/__init__.py`](../../app/backend/schemas/__init__.py)：已有模型的显式兼容导出；模型定义位于同目录的各业务文件。
- [`db.py`](../../app/backend/db.py)：104 行的连接、事务与迁移调度入口。
- [`migrations/__init__.py`](../../app/backend/migrations/__init__.py)：版本常量和 v11–v20 显式顺序清单。
- [`migrations/baseline.py`](../../app/backend/migrations/baseline.py)：原建表、索引及前置兼容字段。
- [`migrations/defaults.py`](../../app/backend/migrations/defaults.py)：迁移后的默认记录、不可变触发器和帮助主题。
- [`migrations/sql.py`](../../app/backend/migrations/sql.py)：不隐式提交事务的 SQL 执行及结构检查辅助函数。

## 2. FastAPI 生命周期

`create_app()` 只装配对象，不初始化数据库；测试为每个用例传入独立配置或 runtime，避免修改 main 全局变量污染其他应用。

`lifespan()` 按固定顺序执行：

1. 创建运行数据和日志目录。
2. `database.initialize()` 创建或迁移数据库。
3. 同步内置角色权限。
4. 写入“本地服务已启动”运行事件。
5. 应用退出时写入停止事件。

该顺序保证权限同步和事件写入不会早于数据库结构。

## 3. 两类认证

HTTP 中间件先检查桌面进程密钥；具体路由再通过 `require_session()` 或 `require_permission()` 检查用户会话。

```text
X-GeoSpectrum-Process-Key
  → 证明请求属于本次桌面 sidecar

Authorization: Bearer <token>
  → 证明当前用户身份与权限
```

两者不能互相替代。浏览器开发模式没有进程密钥时，中间件不启用该门禁；用户认证仍然存在。

## 4. 路由的阅读方法

`api/<module>.py` 中的每个业务路由通常只做四件事：

1. FastAPI/Pydantic 解析输入。
2. `Depends(require_permission(...))` 检查权限。
3. 调用对应应用服务。
4. 把模块异常映射为 `HTTPException`。

业务规则应在模块服务中查找。若规则只存在路由而没有服务测试，通常说明边界开始变差。

`RequestValidationError` 被统一转换为：

```json
{
  "detail": {
    "code": "request_validation_failed",
    "message": "输入数据无效，请检查字段格式和范围",
    "errors": []
  }
}
```

模块异常通常也提供 `code/message/details`。前端依赖稳定错误码，不应只匹配自由文本。

## 5. SQLite 连接和事务

`Database.connect()` 为每个连接启用：

- `foreign_keys = ON`
- `journal_mode = WAL`
- `busy_timeout = 5000`
- `sqlite3.Row` 行对象

`read()` 只管理连接生命周期；`write()` 额外持有进程级写锁，并在正常返回时提交、异常时回滚。模块中的业务数据、审计记录和运行消息应尽量在同一个短事务内写入。

## 6. Schema 版本

当前 `SCHEMA_VERSION = 20`，S10 以前由基线结构表示，v11–v20 通过 `MIGRATIONS` 顺序登记。

阅读迁移时按以下顺序：

1. `Database.initialize()` 开启原有事务，调用 `migrations/baseline.py` 的 `create_baseline()`。
2. db.py 中历史开发标记和旧 JSON 帧的兼容分支。
3. 按 `migrations/__init__.py` 顺序执行 `v11_devices.py` 至 `v20_maintenance.py`，每步写入 schema_migrations。
4. 原测试扩展迁移。
5. `migrations/defaults.py` 写入默认数据和触发器，db.py 最后更新元数据；全部处于同一事务内。

已发布迁移不能原地改义。新字段或表应增加新版本迁移，并覆盖“全新数据库”和“旧版本升级”两条路径。

## 7. 不可变触发器

`migrations/defaults.py` 使用 SQLite 触发器保护已参与业务链路的数据，例如：

- 已发布方法版本。
- 原始硬件帧与通信轨迹。
- 质控和标准曲线快照。
- 曲线计算结果与合并结果。
- 后处理转换、重算和导出记录。
- 报告模型和报告导出。

修改这些数据时应创建新版本或新快照，而不是删除或覆盖原记录。若遇到触发器报错，先找服务中的版本化入口，不要移除触发器规避。

## 8. 集中 schema 的现实边界

计划要求模块拥有自己的表和迁移；当前实现由 `db.py` 调度、`migrations/` 集中定义物理结构，尚未把历史 schema 改写为各业务模块独立迁移。开发时仍要记录逻辑所有权：

- 身份表由 `auth` 拥有。
- 方法和版本由 `methods` 拥有。
- 采集表由 `acquisition`、`dispersion`、`hardware-acquisition` 等各自拥有。
- 分析快照由 `analysis` 拥有。

跨模块服务可以调用公开服务或使用版本化结果，不应随意查询其他模块内部表。当前少量集中服务已有直接联表查询，新增依赖前要评估是否应改为公开应用服务。

## 9. 测试入口

```powershell
cd app
python -m pytest -p no:cacheprovider tests/test_api.py tests/test_schema_migrations.py
python -m pytest -p no:cacheprovider tests/test_auth.py tests/test_architecture.py
```

修改表、索引、触发器或迁移时，还要运行受影响模块测试和 S21 升级测试。

## 2026-09-14 所选依赖的显式装配

Runtime 的方法打印、分析、报告和后处理工厂显式传入各自依赖，构造器不再隐式创建所选跨模块服务。后处理的一次重算使用同一个分析依赖；每次服务工厂调用仍创建本次需要的无状态对象，设备服务的 Runtime 内缓存和事件队列不变。独立测试可以传入受控分析实现，正式工具可以通过 Runtime 工厂构造完整服务。
