# GeoSpectrum

以 **SpecDirect 2.0.2 自动转角光谱仪分析软件** 为业务与旧格式的兼容对象，使用 **FastAPI + React/TypeScript + SQLite + Tauri 2** 构建的 Windows 桌面光谱分析软件。

日常流程是：配置并发布方法 → 建立样品队列 → 摄谱 → 样品分析（测量、重复值检查、逐线曲线复核和结果保存） → 预览、导出或打印报告。色散摄谱用于建立 CCD 点位到波长的关系；蒸发摄谱用于研究信号随时间的变化，和样品摄谱分别提供独立工作区。

## 当前状态（2026-10-21）

- 现有 18 个清单模块、七组导航、25 个正式入口，数据库 schema 为 **23**。菜单按权限及当前方法条件显示和启用。
- 具备方法/谱线、独立蒸发与样品摄谱、完整谱图观察、定量分析、质控、曲线与报告；分析单位支持 `ug/g / mg/g / %`。
- 此前十四项补齐批次记录了后端 322 项、前端 14 项、Rust 文件边界 3 项、浏览器和冻结 QA 桌面各 16 组专项及各 10 组既有操作回归通过。逐项入口和范围见 [实施清单](docs/acceptance-reports/S24/artifacts/2026-10-16-legacy-fourteen-completion/实施清单.md)。
- 当前为未签名内部测试版。真实转角/汞灯协议与硬件、实体打印、签名、干净 Windows 安装升级及正式验收仍按对应报告保留门禁，自动更新关闭。

当前能力与最新证据统一从 [文档索引](docs/README.md) 和 [当前验收状态](docs/acceptance-reports/README.md) 进入。

## 直接运行

本机项目主目录中同时保留 `GeoSpectrum.exe` 与 `geospectrum-backend.exe`，双击前者即可。两文件配套使用；程序已打开时，关闭旧窗口并重开才会载入替换后的版本。正式运行数据使用 `%LOCALAPPDATA%\cn.geospectrum.desktop`。

当前配对交付为 `2026-10-21-page-spacing`：各页面主标题下方的主内容间距统一为蒸发摄谱参考图的24px；保留原有左右缩进、按钮与业务流程。该批未重建安装包。

Git 仓库提交源码与文档，本机 EXE、依赖、缓存、运行数据和旧版资料不随源码分发。只克隆仓库时需要自行构建程序，并准备兼容测试使用的旧版样本。

## 仓库内容

| 路径 | 用途 |
|---|---|
| `app/backend/` | API、业务服务、SQLite 迁移和随包资源 |
| `app/frontend/` | 页面、共用谱图工具和 API 客户端 |
| `app/src-tauri/` | 桌面启动、本机文件能力与 sidecar 生命周期 |
| `app/tests/`、`app/tools/` | 测试、构建、迁移与检查工具 |
| `docs/` | 现行说明、代码导读、计划及历史验收证据 |
| `PLAN.md`、`AGENTS.md` | 范围、确认门禁和协作规则 |

旧资料与阶段记录由文档索引页末的“文档维护”入口查阅。

## Windows 开发运行

需要 Python 3.11+、Node.js 和 pnpm；桌面编译另需 Rust/MSVC Build Tools 与 WebView2。详细构建与 Jet 读取器条件见 [应用开发说明](app/README.md)。以下为 PowerShell 命令。

首次安装依赖，在项目的 `app` 目录执行：

```powershell
cd 'C:\Users\Leo\Desktop\地质局\app'
python -m venv .local\build-venv
.\.local\build-venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd ci
npx.cmd --yes pnpm@11.19.0 --dir frontend install --frozen-lockfile
```

启动后端：

```powershell
$env:SPECTRUM_DATA_DIR = "$PWD\.local\runtime\dev"
.\.local\build-venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8787
```

另开终端启动前端：

```powershell
cd 'C:\Users\Leo\Desktop\地质局\app'
npm.cmd run frontend:dev
```

打开 [开发前端](http://127.0.0.1:5173)，首次使用时按页面提示创建管理员。后端提供 [API 文档](http://127.0.0.1:8787/docs)。开发数据库与用户运行库分开。

常用检查，在 `app` 目录执行：

```powershell
.\.local\build-venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend test
npm.cmd run frontend:build
```

兼容测试依赖本地旧版资料；浏览器测试另需 Playwright。单个批次的定向通过不能代表全量测试或真实仪器验收。

## 阅读入口

- [文档索引](docs/README.md)：现行说明、最新变化和证据入口。
- [使用说明](docs/使用与说明/GeoSpectrum_使用说明.md) / [离线手册](docs/使用与说明/GeoSpectrum_使用手册.html)：实际操作步骤。
- [项目阅读指南](docs/项目阅读指南.md) / [代码导读](docs/代码导读/README.md)：从页面追踪 API、保存字段和消费者。
- [总体计划](PLAN.md) / [验收状态](docs/acceptance-reports/README.md)：授权范围和未关闭门禁。
