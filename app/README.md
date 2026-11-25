# GeoSpectrum 应用开发说明

更新日期：2026-10-18。`app/` 是新版正式实现；项目介绍见 [根 README](../README.md)，实际操作见 [使用说明](../docs/使用与说明/GeoSpectrum_使用说明.md)。

## 当前工程状态

18 个模块由 `backend/modules/manifest.py` 注册，前端呈现七组导航、25 个正式入口。SQLite 当前 schema 为 **23**，版本与迁移顺序定义在 `backend/migrations/__init__.py`。

当前为未签名内部测试版，最新交付与未关闭项见 [当前验收状态](../docs/acceptance-reports/README.md)。

## 源码组织

| 路径 | 职责 |
|---|---|
| `backend/main.py`、`runtime.py` | FastAPI 生命周期与显式服务装配 |
| `backend/api/`、`schemas/` | 按业务划分的路由及请求/响应契约 |
| `backend/modules/` | 应用服务、算法、设备适配与领域数据处理 |
| `backend/db.py`、`migrations/` | 连接/事务、S10 基线、v11–v23 顺序迁移和默认数据 |
| `backend/printing/`、`resources/` | 公共打印调度与冻结程序必需资源 |
| `frontend/src/App.tsx`、`layout/` | 身份入口、跨页状态、导航与页面分派 |
| `frontend/src/pages/`、`components/` | 业务工作区与共用谱图工具 |
| `frontend/src/api/`、`platform/` | HTTP/WebSocket、本机文件、剪贴板与确认交互 |
| `src-tauri/` | 单实例、随机本地端口、进程密钥、sidecar 和原生保存 |
| `tests/`、`tools/` | 自动化验证与构建工具 |
| `.local/` | 已忽略的开发数据、缓存、诊断与本机发布备份 |

主要大模块现已改为包：`methods/`、`analysis/`、`acquisition/`、`devices/`、`dispersion/`、`hardware_acquisition/`、`mercury_calibration/`、`spectrum_migration/`、`reports/` 等。具体入口见 [代码导读](../docs/代码导读/README.md)，不要再查已移除的同名单文件。

方法使用草稿/发布与不可变版本；样品摄谱和蒸发摄谱有独立表单及任务列表，共用采集引擎。谱图观察与分析保留原始输入、曝光段及结果快照。`legacy_2_0_2` 和 `modern_v1` 两种计算档案同时保留。界面隐藏的兼容字段仍在载荷及必要输出中，不能按“没有编辑框”删除字段。

## 开发环境（Windows PowerShell）

浏览器开发需要 Python 3.11+、Node.js、pnpm。前端测试使用 Node 的 `--experimental-strip-types`，需支持该选项的 Node 版本。桌面编译另需 Rust stable、MSVC Build Tools 和 WebView2。构建旧 Access 读取器需要 .NET 8 SDK，运行 win-x86 读取器需要 x86 .NET 8 Runtime 与 32 位 Jet 4.0；读取器不可用不影响常规服务启动。

以下初始化只需执行一次：

```powershell
cd 'C:\Users\Leo\Desktop\地质局\app'
python -m venv .local\build-venv
.\.local\build-venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd ci
npx.cmd --yes pnpm@11.19.0 --dir frontend install --frozen-lockfile
```

桌面工具使用 `app/package-lock.json`；前端使用 `frontend/pnpm-lock.yaml`。

## 本地运行

终端 1，启动隔离开发后端：

```powershell
cd 'C:\Users\Leo\Desktop\地质局\app'
$env:SPECTRUM_DATA_DIR = "$PWD\.local\runtime\dev"
.\.local\build-venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8787
```

终端 2，启动浏览器前端：

```powershell
cd 'C:\Users\Leo\Desktop\地质局\app'
npm.cmd run frontend:dev
```

访问 [前端](http://127.0.0.1:5173) 与 [API 文档](http://127.0.0.1:8787/docs)。若使用 Tauri 开发模式，在终端 2 改为：

```powershell
$env:GEOSPECTRUM_DEV_API_BASE = 'http://127.0.0.1:8787'
npm.cmd exec -- tauri dev
```

正式运行数据默认在 `%LOCALAPPDATA%\cn.geospectrum.desktop`；开发/测试显式指定隔离目录，避免改动现有用户数据库。

## 软件激活与模块远程诊断

### 软件激活

既有部署默认沿用原授权策略。需要启用到期控制时，由部署方给启动 GeoSpectrum 的环境配置 `GEOSPECTRUM_ACTIVATION_PUBLIC_KEY`，值为 Ed25519 原始 32 字节公钥的 Base64。部署方在可信环境保管独立的私钥。配置后，管理员在「帮助 → 关于软件 → 软件激活」查看安装标识，并交给授权签发方。以下命令在签发环境的 `app` 目录执行，示例中的日期、标识及路径需替换为获准值。

```powershell
python tools/sign_activation.py --private-key 'D:\授权\issuer.pem' --installation-id '现场安装标识' --expires-at '2027-01-01T00:00:00+08:00' --output 'D:\授权\activation.json'
```

管理员在同一页面导入签名 JSON。续期使用同一安装标识及更晚的到期时间。验签、安装标识匹配和到期判断均在本机完成。受管部署到期后可查看历史资料、导入续期文件、继续或停止已开始的任务；新测量、摄谱和预热需有效授权。迁移受管部署前应妥善保管数据目录内的 `activation-installation.id` 和 `activation.json`，并保持受信任验签配置。离线到期判断依赖受管工作站的系统时钟与部署配置保护。

### 跨机器读取诊断

1. 现场管理员进入「帮助 → 关于软件 → 模块远程诊断」，选择时长并点击「开启诊断共享」。通过已批准的支持渠道向指定人员提供现场回环端口及临时访问令牌。
2. 支持人员使用已有可信网络通道和经现场 IT 授权的 SSH 转发账号。SSH 服务应与 GeoSpectrum 运行在同一现场主机上，并将该账号的转发目标限定为本次诊断端口。若现场主机只能经内网访问，应先接入已有的受管 VPN 或跳板。下面以现场端口 `52525`、支持端口 `18787` 为例。

```powershell
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18787:127.0.0.1:52525 tech@site-host
```

3. 支持人员在另一个 PowerShell 窗口输入临时令牌并读取快照。现场管理员可在同一授权期内点击「刷新共享快照」，支持人员重新执行读取即可获取新的自检结果和最多 40 条日志中的脱敏事件。快照中的 `checked_at` 标识本次采样时间。

```powershell
$supportToken = Read-Host '临时访问令牌'
Invoke-RestMethod 'http://127.0.0.1:18787/api/v1/support/snapshot' -Headers @{Authorization = "Bearer $supportToken"} | ConvertTo-Json -Depth 8
```

4. 排查结束后，现场点击「结束诊断共享」，支持端按 Ctrl+C 关闭转发。会话到期、开启者退出登录、授权被撤销或程序退出时，临时令牌失效。业务 API 继续使用原有回环端口与桌面进程密钥。诊断端口只接受固定快照的授权读取。

转发配置可参考 [OpenSSH 客户端手册](https://man.openbsd.org/ssh#L)和 [服务端 PermitOpen 说明](https://man.openbsd.org/sshd_config#PermitOpen)。

## 常用验证

在 `app` 目录执行，按改动风险选择：

```powershell
.\.local\build-venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend test
npm.cmd run frontend:build
.\.local\build-venv\Scripts\python.exe tools/generate_manifest.py
cargo test --manifest-path src-tauri/Cargo.toml
```

业务定向测试通常为 `tests/test_sXX_*.py`。新补齐流程见 `test_legacy_operator_workflows.py`、`test_gap_workflows.py`、`test_spec_gap_closure.py`；单位链见 `test_analysis_units.py`。前端 `npm test` 现覆盖数值输入、传输、单位和旧版观察规则。

浏览器集成脚本在 `tests/*.mjs`，需要 Playwright、隔离后端/前端及相应种子数据。旧格式测试还依赖本机旧版资料或指定夹具。完整后端测试应在 `app/` 下运行；不要把历史定向测试数量写成当前全量结果。

## 内部测试包构建

在当前终端激活构建环境后运行：

```powershell
cd 'C:\Users\Leo\Desktop\地质局\app'
. .\.local\build-venv\Scripts\Activate.ps1
npm.cmd run release:internal
```

该命令顺序重建并验证 sidecar，再构建 Tauri/NSIS 并生成发布清单。失败时不能复用旧 sidecar 冒充本次产物。单独的构建/探针入口为 `tools/build_sidecar.py`、`tools/verify_sidecar.py`、`tools/build_release_manifest.py`。

本机根目录 `GeoSpectrum.exe` 与 `geospectrum-backend.exe` 是配套入口。最新交付见 [十项补齐验证](../docs/acceptance-reports/S24/artifacts/2026-10-16-legacy-ten-completion/verification.json)；本批未更新安装包。

`tools/measure_tauri_startup.py` 只观察调试进程并主动收尾，不能证明 UI 就绪或自然退出。冻结 sidecar、浏览器、真实 QA WebView2、实体打印、硬件在环、干净系统安装和签名证据各自独立，详情按 [验收索引](../docs/acceptance-reports/README.md) 追踪。

---

[文档维护](../docs/参考资料/文档维护.md)
