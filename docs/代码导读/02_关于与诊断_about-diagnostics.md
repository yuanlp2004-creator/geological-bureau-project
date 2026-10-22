# 关于软件与管理员诊断导读（兼容键 `about-diagnostics`）

## 1. 模块定位

“帮助 → 关于软件”只显示软件名称、版本和版权。“系统管理 → 备份与维护”中的系统诊断仅对具备 `maintenance.write` 的管理员开放，显示本地运行、数据库和模块检测结果。“构建与许可详情”已移除。两处只读显示均不执行修复或维护动作。

清单定义在 `ABOUT_MANIFEST`，权限为 `about.read`，依赖 `core`。

## 2. 代码入口

- API：[`backend/api/system.py`](../../app/backend/api/system.py) 中的 `/about`、`/api/v1/about`、`/api/v1/capabilities`、`/api/v1/diagnostics`
- 模块清单：[`backend/modules/manifest.py`](../../app/backend/modules/manifest.py)
- 数据模型：`schemas/system.py` 中的 `AboutResponse`、`DiagnosticsResponse`、`CapabilitiesResponse`
- 前端：`pages/about/AboutPage.tsx`；管理员诊断在 `pages/maintenance/SystemDiagnostics.tsx`（相对于 frontend/src/）。
- 测试：`test_api.py`、`test_architecture.py`

## 3. 三类响应

### 关于信息

`about()` 返回产品名、显示名称、版本和版权，并保留既有响应字段兼容。运行时、数据库路径、模块、许可和构建详情仅对具备维护操作权限的账号返回，其他账号收到空值。版权依据开发合同第8.1条归甲方“湖北华祥地质环境检测科技有限公司”。

### capability 清单

`_capabilities()` 调用 `registered_manifests()` 并先执行 `validate_manifests()`，再输出模块键、版本、API 前缀、前端路由、权限、审计动作和导航条目。

前端导航以该响应为事实来源。这里的 `enabled` 表示模块已构建接入，不表示真实硬件门禁已关闭；应同时查看导航条目的 `status`。

### 诊断信息

`diagnostics()` 提供数据库路径、日志路径、schema 版本、SQLite 完整性、WAL、外键、事件数量和清单校验状态。诊断读取不应改变数据库。

模块检测声明随 `ModuleManifest` 注册：只读路径、所需数据表、响应类型和硬件说明。`api/module_diagnostics.py`先检查清单、表结构及实际路由，再通过本应用的ASGI传输执行GET查询，沿用当前会话和桌面进程密钥；无网络外发、无权限绕过。最多4项并行，每项3秒超时；最后传播依赖模块的异常或未检测状态。

前端清单只读取本次诊断响应中的模块状态及检测时间，不使用静态enabled推定可用。状态分别为软件可用、异常、未启用、无检测权限及未检测。失败或刷新时清除旧结果；硬件模块注明实机边界。这不是完整业务验收，也不会启动设备或写入业务数据。

## 4. 权限边界

关于软件使用 `about.read`；诊断API使用 `maintenance.write`，前端仅在维护页按需请求。普通登录、工作台及关于页不触发完整诊断。只读审计员保留 `maintenance.read` 和备份查看，但不能显示或请求系统诊断。导航隐藏和后端403同时生效。

系统管理员、方法管理员、分析员和只读审计员的内置权限均包含 `about.read`；自定义角色可以不包含。

## 5. 常见排查

- 页面缺少模块：先看 `/api/v1/capabilities`，再看清单注册，而不是先改前端。
- schema 版本异常：转到 `db.py` 和 `upgrade.py`，诊断页本身不负责升级。
- 安装包版本与页面不一致：核对 `backend/__init__.py`、Tauri `Cargo.toml/tauri.conf.json` 和发布清单。
- 诊断接口403：核对 `maintenance.write`；仅有 `about.read` 或 `maintenance.read` 不能访问。

## 6. 修改检查

- 新诊断字段不得泄露密码、令牌、进程密钥或原始通信内容。
- 关于页版本必须与构建元数据一致。
- capability 结构变化必须同步 `frontend/src/api/index.ts`。
- 运行 `test_api.py`、`test_auth.py` 和 `test_architecture.py`。
