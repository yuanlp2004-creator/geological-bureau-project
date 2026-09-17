# 关于与诊断模块导读（`about-diagnostics`）

## 1. 模块定位

本模块向用户和维护人员公开版本、构建、模块清单及本地运行诊断。它是只读模块，不负责修复数据库或执行维护动作。

清单定义在 `ABOUT_MANIFEST`，权限为 `about.read`，依赖 `core`。

## 2. 代码入口

- API：[`backend/api/system.py`](../../app/backend/api/system.py) 中的 `/about`、`/api/v1/about`、`/api/v1/capabilities`、`/api/v1/diagnostics`
- 模块清单：[`backend/modules/manifest.py`](../../app/backend/modules/manifest.py)
- 数据模型：`schemas/system.py` 中的 `AboutResponse`、`DiagnosticsResponse`、`CapabilitiesResponse`
- 前端：`pages/about/AboutPage.tsx`（相对于 frontend/src/）。
- 测试：`test_api.py`、`test_architecture.py`

## 3. 三类响应

### 关于信息

`about()` 返回产品名、显示名称、版本、API 版本、阶段、运行时、数据库类型、许可和构建信息。它还列出当前模块，用于核对安装包实际能力。

### capability 清单

`_capabilities()` 调用 `registered_manifests()` 并先执行 `validate_manifests()`，再输出模块键、版本、API 前缀、前端路由、权限、审计动作和导航条目。

前端导航以该响应为事实来源。这里的 `enabled` 表示模块已构建接入，不表示真实硬件门禁已关闭；应同时查看导航条目的 `status`。

### 诊断信息

`diagnostics()` 提供数据库路径、日志路径、schema 版本、SQLite 完整性、WAL、外键、事件数量和清单校验状态。诊断读取不应改变数据库。

## 4. 权限边界

关于与诊断包含本地路径、版本和模块能力，因此需要 `about.read`。导航隐藏和后端 403 必须同时存在，不能只依赖前端。

系统管理员、方法管理员、分析员和只读审计员的内置权限均包含 `about.read`；自定义角色可以不包含。

## 5. 常见排查

- 页面缺少模块：先看 `/api/v1/capabilities`，再看清单注册，而不是先改前端。
- schema 版本异常：转到 `db.py` 和 `upgrade.py`，诊断页本身不负责升级。
- 安装包版本与页面不一致：核对 `backend/__init__.py`、Tauri `Cargo.toml/tauri.conf.json` 和发布清单。
- 诊断接口 403：核对角色权限同步和 `about.read`。

## 6. 修改检查

- 新诊断字段不得泄露密码、令牌、进程密钥或原始通信内容。
- 关于页版本必须与构建元数据一致。
- capability 结构变化必须同步 `frontend/src/api/index.ts`。
- 运行 `test_api.py`、`test_auth.py` 和 `test_architecture.py`。
