# GeoSpectrum

SpecDirect 2.0.2 的新架构实现。`app/` 是正式实现目录；`Spec Source/`、`Spec2.02/`、`SpecFile/` 和 `UI测试/` 仍然是只读资料或视觉参考。

第一次接手或需要跨前端、后端、数据库与 Tauri 追踪功能时，先读 [`项目阅读指南.md`](../docs/项目阅读指南.md)。

## 后端目录

`backend/` 直接作为 Python 包，代码、模块和运行资源都从这一层组织：

```text
backend/
├─ __init__.py          包与版本号
├─ main.py             FastAPI 入口
├─ runtime.py          每个应用的服务、会话和事件状态
├─ api/                按业务划分的全部接口、事件与公共请求边界
├─ config.py           运行配置
├─ db.py               数据库连接、事务与迁移调度
├─ migrations/         基线、v11–v20 历史迁移与默认数据
├─ auth.py             身份服务
├─ schemas/            按业务划分的全部 API 数据结构
├─ services.py         公共应用服务
├─ upgrade.py          数据升级
├─ sidecar_entry.py    桌面后端启动入口
├─ requirements.txt    Python 依赖
├─ modules/            业务模块
└─ resources/          模拟样本与旧数据读取脚本
```

在 `app/` 目录启动后端：`python -m uvicorn backend.main:app --host 127.0.0.1 --port 8787`。

结构重构 R3 已完成：`main.py` 只保留应用工厂与生命周期（44 行）。全部接口按业务位于 `api/`，WebSocket 位于 `api/events.py`，路由统一由 `api/__init__.py` 显式注册。所有模型定义已归入 `schemas/` 各业务文件，包入口仅作兼容导出。测试使用 `create_app(AppConfig(data_dir=...))` 创建隔离应用，通过 `application.state.runtime` 访问测试服务，不修改 main 的全局数据库或会话。

## 前端请求目录

R4 已将原 `frontend/src/api.ts` 拆分：`api/index.ts` 保留页面调用兼容，18 个业务文件各自保存请求和类型，`api/client.ts` 负责共享 HTTP 传输，`api/events.ts` 负责 WebSocket 地址；`platform/runtime.ts` 与 `platform/files.ts` 分别负责桌面握手及文件能力。

R5 已把页面归入 `pages/`、应用布局归入 `layout/`、公共组件归入 `components/`。`App.tsx` 为 82 行认证入口，`layout/WorkspaceApp.tsx` 保留原跨页面状态和分派。CSS 文件按用途归位，`styles/index.ts` 保持原加载顺序，构建 CSS 与拆分前逐字节一致。

浏览器集成验证：`npm.cmd --prefix frontend run test:api`。需安装 Playwright，或用 `PLAYWRIGHT_MODULE_PATH` 指定可用的 Playwright 包目录；默认使用本机 Edge，无需前台操作。测试使用隔离临时数据库；Tauri 桥接部分是受控模拟，未操作原生文件对话框。

页面回归：`npm.cmd --prefix frontend run test:pages`，复用同一隔离环境，增加方法保存/非法输入、导航切换、主题与只读权限检查。

## 已构建程序的位置

按用户要求，当前内部测试程序位于项目主目录的 [`GeoSpectrum.exe`](../GeoSpectrum.exe)，直接双击启动；同目录的 `geospectrum-backend.exe` 必须与主程序一起保留。安装包保留在 `.local/releases/0.1.0/`。正常启动仍使用 `%LOCALAPPDATA%\cn.geospectrum.desktop`，移动程序不会移动用户数据。

`.local/releases/` 仅保存本机安装包和整理清单并已被 Git 忽略；正式构建位置仍为 `src-tauri/target/`，发布清单与说明仍归档于 `docs/releases/`。旧版本回退备份保留在 `.local/rebuild-20260905/previous/`；独立便携演示版保留在 `docs/releases/0.1.0/GeoSpectrum_便携演示版/`。

## 已完成范围（S01–S22 软件闭环）

- FastAPI 本地服务：健康检查、关于/诊断、能力清单、软件设置、运行事件。
- SQLite：WAL、外键、版本化迁移，保存元数据、设置和运行事件。
- React/TypeScript：八组任务导航、权限与当前方法门禁、页内视图直达、工作台、消息面板、设置页、关于/诊断页。
- Tauri 2：单实例插件、sidecar 生命周期入口、受控文件/目录对话框和 PDF/CSV/TXT/LOG/SAM 统一“另存为”命令；浏览器开发模式保留标准下载回退。
- 架构工具：模块清单生成器和依赖/注册约束测试。
- 本地身份：首次管理员、Argon2id 密码、角色权限、进程内会话、用户/角色管理和审计。
- 方法与条件：不可变版本、草稿/发布、当前方法、新建/复制/重命名/启停/软删除、CCD/色散和采集/质控/转角条件。
- 分析谱线：基线/分析/内标/定位四类谱线、CCD/转角可检测判定、引用与三种内标、峰值/拟合/单位/超限参数、标准点和关键波段优先级。
- 方法预览与打印：持久化打印机/纸张/方向/边距/版式参数，统一分页模型生成 HTML 预览和可检索文字 PDF，并提供系统打印与可自动验收的内置 PDF 虚拟打印机；失败任务保留渲染输入和错误 PDF。
- 旧版迁移：32 位 Jet 4.0 读取器只打开操作系统临时副本；FastAPI 提供暂存、字段/BLOB/引用校验、单事务提交、幂等指纹和迁移报告，导入 `DIRECT.MTD/CFG/OPT`，不导入旧样品与分析结果。
- 旧谱数据与结果迁移：只读解析 CDT/CMT/EDT/WDT 和 DAT/PDT，保留原件指纹、数组形状、矩阵元数据与孤立结果；谱图查看支持 CCD/波长坐标、筛选、可见范围导出和打印。
- 设备与采集：设备适配器、模拟器、色散采集与不可变校准、样品队列和重复采集、自动转角安全状态机、汞灯调试与校准的软件闭环；真实转角和汞灯协议/硬件仍受 S14、S15 外部门禁约束。
- 定量分析：参考线校正、谱线定位、最大单点/高斯计算、三种内标、旧版/现代计算档案、逐谱线慢进干预及可重放输入与结果矩阵。
- 重复质控与标准曲线：均值/极差/标准差/RSD/ID、提示接受与重复值剔除恢复，直线/二次/三次/样条及普通/对数坐标，标准点启停与强度修正、不可变曲线快照、样品结果合并、图像/文本预览和 PDF 打印。
- 报告预览与导出：报告编号/版本/模板、常规/交换排列、筛选与批量选择、预览确认门禁，以及文本、CSV、Excel、PDF、保存和打印输出；所有渲染输入、版本、同名策略和审计事件可追溯。

S21 已完成随机本地端口、一次性进程密钥、升级前备份与副本迁移、测试构建模块模板、发布清单和 Windows x64 Tauri 构建链加固。NSIS 内嵌 WebView2 离线安装器；运行数据使用 `%LOCALAPPDATA%\cn.geospectrum.desktop`，并在验证后只读复制旧 `%LOCALAPPDATA%\GeoSpectrum` 数据。代码签名、干净 Windows 10/11 安装升级复验和真实转角/汞灯硬件在环证据仍是正式发布门禁，因此当前只能生成未签名内部测试包，自动更新保持关闭。

内部测试包构建：

```powershell
cd app
$python311 = 'C:\Path\To\Python311\python.exe'
& $python311 -m venv .local\build-venv
& .\.local\build-venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PATH = "$(Resolve-Path .\.local\build-venv\Scripts);$env:PATH"
npm.cmd run release:internal
```

该命令会先重建并验证 FastAPI sidecar，再生成 NSIS 包和 `docs/releases/<version>/internal-test-manifest.json`；任何一步失败都不会把旧 sidecar 标记为可发布包。

旧方法读取器的 .NET 8 `win-x86` 工程和开发环境的 32 位 Windows PowerShell 回退实现位于 `tools/legacy-mdb-reader/`。没有 32 位 Jet 时仅迁移入口不可用，FastAPI 常规启动不受影响。

## 开发环境初始化（Windows）

需要 Python 3.11+、Node.js、Rust stable/MSVC Build Tools 和 WebView2；编译旧 Access
读取器时还需要 .NET 8 SDK，运行其 win-x86 产物还需要 x86 .NET 8 Runtime。在 `app/`
目录执行：

```powershell
python -m venv .local\build-venv
$localRoot = (Resolve-Path .local).Path
$env:PIP_CACHE_DIR = Join-Path $localRoot 'pip-cache'
$env:npm_config_cache = Join-Path $localRoot 'npm-cache'
& .\.local\build-venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd ci
corepack.cmd prepare pnpm@11.19.0 --activate
corepack.cmd pnpm --dir frontend install --frozen-lockfile --store-dir (Join-Path $localRoot 'pnpm-store')
```

Python、pnpm/NuGet 缓存和开发数据库均应放入已忽略的 `app/.local/`，不要在项目根目录
保存运行数据或临时输出。

## 本地运行

后端（终端 1）：

```powershell
cd app
$python = '.\.local\build-venv\Scripts\python.exe'
$env:SPECTRUM_DATA_DIR = (Join-Path (Resolve-Path .local).Path 'runtime\dev')
& $python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8787
```

浏览器前端（终端 2）：

```powershell
cd app
npm.cmd run frontend:dev
```

Tauri 桌面开发模式同样复用终端 1 的后端（终端 2）：

```powershell
cd app
$env:GEOSPECTRUM_DEV_API_BASE = 'http://127.0.0.1:8787'
npm.cmd exec -- tauri dev
```

架构测试和清单生成：

```powershell
cd app
$python = '.\.local\build-venv\Scripts\python.exe'
& $python -m pytest -q
& $python -m coverage run --source=backend -m pytest -q
& $python -m coverage report -m
& $python tools/generate_manifest.py
& $python tools/build_sidecar.py
& $python tools/verify_sidecar.py
& $python tools/measure_tauri_startup.py
npm.cmd run tauri:build
```

R6 数据库整理已完成：db.py 为 104 行，版本保持 v20；migrations/ 显式登记迁移，baseline.py 与 defaults.py 保留原 SQL 和执行顺序。升级验证见 `tests/test_schema_migrations.py` 与 `tests/test_s21_release.py`。


## 2026-09-14 结构重构交付

R0–R7 已完成。根目录 `GeoSpectrum.exe` 和配套 `geospectrum-backend.exe` 已更新；内部安装包在 `.local/releases/2026-09-14-refactor-r7/`。验收记录见 [S21](../docs/acceptance-reports/S21/验收报告.md)，本次发布清单独立归档在 [R7 发布目录](../docs/releases/0.1.0/2026-09-14-refactor-r7/)。

原生 PDF 保存、目录选择/取消、单实例与正常关闭已在真实 release 程序中验证；浏览器脚本的受控桥接检查仍单独保留。未签名内部包不能替代干净 Windows 安装升级卸载或真实硬件验收。

`tools/measure_tauri_startup.py` 只观察调试进程存活并终止测试进程，不是 UI 就绪时间或自然退出验收。正式 release 自然关闭记录见 R7 报告。发布清单可用 `--output-dir` 为每次交付指定独立归档目录。


### analysis 模块补充重构（2026-09-14）

原 1188 行 `backend/modules/analysis.py` 已改为 `analysis/` 包：运行流程在 service.py，纯算法在 algorithms.py，质控在 quality.py，曲线在 curves.py，预览/PDF 在 printing.py，共享查询和结果装配在 repository.py。最大文件 service.py 为 343 行；公开 AnalysisService/AnalysisError 和算法入口保持，17 个公开方法签名不变。

验证覆盖原 S16/S17 黄金样本、后处理与报告，以及质控/拟合/打印审计失败整笔回滚。根目录仅更新配套后端，桌面壳与前端保持 R7 版本；R7 安装包保留当时完整快照，本轮没有重新制作安装包。


### methods 与 legacy_migration 补充重构（2026-09-14）

`backend/modules/methods/` 按条件值、几何、校验、共享查询、版本事务与运行状态组织，最大文件 300 行；`legacy_migration/` 按读取器、配置、BLOB 记录、归一化、源指纹与暂存/提交组织，最大文件 301 行。原服务导出与消费者调用保持。

全量 169 项、联合定向 31 项、浏览器与冻结真实旧库迁移通过。根目录配套后端已更新；桌面壳与前端不变，R7 安装包仍为当时快照。详见 [S21](../docs/acceptance-reports/S21/验收报告.md)。

### postprocessing 与 method_printing 补充重构（2026-09-14）

`backend/modules/postprocessing/` 按转换、重算、导出、查询和编解码组织，最大文件 263 行；`backend/modules/method_printing/` 按服务入口、文档分页、渲染组织。D1 将打印机枚举与系统调度提到 `backend/printing/`，方法与报告共同使用，报告不再构造方法打印服务。D1 的源码验证见 [S21 报告](../docs/acceptance-reports/S21/验收报告.md)；本阶段未更新 EXE 或安装包。此前 171 项测试及冻结专项对应 [上一交付快照](../docs/releases/0.1.0/2026-09-14-postprinting-refactor/verification.json)。

### 后端内部解耦 D2–D4（2026-09-14）

所选服务由 `Runtime` 显式装配；单独构造 AnalysisService、MethodPrintService、PostProcessingService、ReportService 时必须传入依赖，没有旧构造回退。一般工具可使用 `Runtime(config, database=database)` 的服务工厂。方法快照归 `modules/methods/snapshots.py`；已有采集导入归 `modules/acquisition_import.py`，事务由后处理 `conversion.py` 内的 ConversionUnitOfWork 统一提交；旧 PDT 纯计算归 `postprocessing/legacy_calculation.py`，打印内部设置归 `method_printing/settings.py`。

最终 188 项后端测试、OpenAPI/打印/导出对比及无界面页面回归通过。源码与本机 EXE/安装包是不同快照：本轮未更新可执行分发。范围、剩余耦合与验证命令见 [解耦计划](../docs/规划与计划/INTERNAL_DECOUPLING_PLAN.md) 和 [S21 验收报告](../docs/acceptance-reports/S21/验收报告.md)。
