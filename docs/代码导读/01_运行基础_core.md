# 运行基础模块导读（`core`）

## 1. 模块定位

`core` 提供所有业务模块共同依赖的本地运行基础：健康检查、软件设置、运行事件和工作台入口。它不负责用户认证、具体业务数据或桌面进程管理。

清单定义在 [`CORE_MANIFEST`](../../app/backend/modules/manifest.py)，主要权限是 `settings.read/write` 和 `runtime-events.read/write`。

## 2. 代码入口

- 配置：[`backend/config.py`](../../app/backend/config.py)
- 应用服务：[`backend/services.py`](../../app/backend/services.py)
- API 路由：[`backend/api/system.py`](../../app/backend/api/system.py) 中的 `/health`、`/api/v1/settings`、`/api/v1/logs`
- 服务装配：[`backend/runtime.py`](../../app/backend/runtime.py)；请求通过 `api/dependencies.py` 获取当前应用的运行容器。
- 请求模型：[`backend/schemas/system.py`](../../app/backend/schemas/system.py) 中的设置和运行事件模型
- 前端：`pages/workspace/WorkspacePage.tsx、components/MessagePanel.tsx、pages/settings/SettingsPage.tsx`（相对于 frontend/src/）。
- 测试：`test_api.py`、`test_config.py`、`test_architecture.py`

## 3. 配置与运行目录

`AppConfig` 从 `SPECTRUM_DATA_DIR` 读取显式目录；未设置时使用 Windows 本地应用数据目录。派生路径包括：

- `geospectrum.sqlite3`
- `logs/runtime.jsonl`

代码读取时要区分两类设置：

- 启动期环境配置：由 `config.py` 决定，例如数据库实际位置。
- 用户软件设置：由 `AppService` 存入 `app_settings`，例如界面主题、日志级别和打印参数。

修改用户设置不会重新定位已经打开的数据库。

## 4. 软件设置流程

`DEFAULT_SETTINGS` 分为 `directories`、`logging`、`display`、`printing`、`time` 五组。`get_settings()` 的流程是：

1. 复制默认设置。
2. 逐条读取 `app_settings`。
3. 用对应 Pydantic 模型验证合并后的完整分组。
4. 对未知键、非法 JSON 或非法值回退默认值。
5. `_repair_invalid_settings()` 只删除仍然匹配原始坏值的记录，并写审计事件。

`update_settings()` 先完整验证所有分组，再在一个事务中写入。任意字段失败时不能部分保存，也不能记录成功审计。

## 5. 运行事件与文件日志

`append_event()` 同时承担：

- 向 `runtime_events` 插入结构化事件。
- 按日志级别决定是否写入 JSONL 文件。
- 对 token、password、authorization、secret、key 等敏感字段递归脱敏。
- 达到大小上限时轮转日志，并删除超过保留天数的归档。

运行事件面向状态与操作反馈；审计事件面向责任追踪，两者不能混用。清空运行消息不会删除审计记录。

## 6. 健康检查

`health()` 返回应用名、版本、运行时长、数据库可用性和当前时间。它用于 Tauri/sidecar 启动验证，不代表所有业务模块或真实硬件已经可用。

## 7. 数据表

- `app_metadata`：schema 版本和应用元数据。
- `app_settings`：扁平键与 JSON 值。
- `runtime_events`：可筛选、可清理的运行消息。
- `audit_events`：设置修改和清理操作的不可编辑审计。

## 8. 推荐阅读顺序

`DEFAULT_SETTINGS` → `get_settings()` → `update_settings()` → `_redact()` → `append_event()` → `health()` → `api/system.py` 对应路由 → 前端设置页和消息面板。

## 9. 修改检查

- 新设置字段是否同时更新默认值、Pydantic 模型、前端类型和界面。
- 非法值是否原子失败。
- 敏感字段是否会进入 JSONL。
- 日志级别是否只影响文件输出，不破坏数据库事件。
- 修改后运行 `test_config.py`、`test_architecture.py` 和相关 API 测试。
