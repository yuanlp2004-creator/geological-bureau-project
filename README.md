# GeoSpectrum

当前摄谱界面（2026-10-25）：摄谱激发区域按旧版截图重排：顶部谱线／只读波长与曝光区间，左侧三列样品表，中间紧凑工具与大谱图，右侧常驻样号／重复摄谱和四个纵向激发按钮。图标16像素，普通工具24像素、窄窗口谱图工具20像素；条件与命名默认收起，进度移到底部。预录样号可直接切换并带出次数，使用当前任务条件，不自动激发。浏览器17组、实际QA桌面15组与各8布局；采集回归各5组／8布局、前端15项、后端16项通过。后端源码及字节保持，配对程序已备份更新，关闭重开生效；安装包未更新。见[布局对照](docs/acceptance-reports/S24/artifacts/2026-10-25-legacy-excitation-layout/布局对照.md)。

以 **SpecDirect 2.0.2 自动转角光谱仪分析软件** 为业务与旧格式的兼容对象，使用 **FastAPI + React/TypeScript + SQLite + Tauri 2** 构建的 Windows 桌面光谱分析软件。

日常流程是：配置并发布方法 → 建立样品队列 → 摄谱 → 样品分析（测量、重复值检查、逐线曲线复核和结果保存） → 预览、导出或打印报告。色散摄谱用于建立 CCD 点位到波长的关系；蒸发摄谱用于研究信号随时间的变化，和样品摄谱分别提供独立工作区。

## 当前状态（2026-10-25）

- 现有 18 个清单模块、七组导航、25 个正式入口，数据库 schema 为 **23**。菜单按权限及当前方法条件显示和启用。
- 具备方法/谱线、独立蒸发与样品摄谱、完整谱图观察、定量分析、质控、曲线与报告；分析单位支持 `ug/g / mg/g / %`。
- 此前十四项补齐批次记录了后端 322 项、前端 14 项、Rust 文件边界 3 项、浏览器和冻结 QA 桌面各 16 组专项及各 10 组既有操作回归通过。逐项入口和范围见 [实施清单](docs/acceptance-reports/S24/artifacts/2026-10-16-legacy-fourteen-completion/实施清单.md)。
- 当前为未签名内部测试版。真实转角/汞灯协议与硬件、实体打印、签名、干净 Windows 安装升级及正式验收仍按对应报告保留门禁，自动更新关闭。

当前能力与最新证据统一从 [文档索引](docs/README.md) 和 [当前验收状态](docs/acceptance-reports/README.md) 进入。

## 直接运行

本机项目主目录中同时保留 `GeoSpectrum.exe` 与 `geospectrum-backend.exe`，双击前者即可。两文件配套使用；程序已打开时，关闭旧窗口并重开才会载入替换后的版本。正式运行数据使用 `%LOCALAPPDATA%\cn.geospectrum.desktop`。

此前配对交付为 `2026-10-25-full-spectroscopy`：40枚旧版图标已全部用本地Qwen Image 2.1重绘，覆盖38个按钮位置及解锁等替代状态。三类摄谱恢复左侧谱带／帧列表、中间谱图与工具、右侧样号与激发控制；补上一／下一谱带和CCD、1:1／1:4／真实十倍CCD、独立纵向还原、已保存谱带打印及结束返回。正式样品完成后选中最新保存谱带，色散完成后显示燃烧均值；当前色散任务可展开谱线定位与拟合。后台只补物理比例所需只读元数据，schema23及原采集规则保持。浏览器13组、实际QA桌面12组与各6布局，采集回归各5组／8布局通过；后端16项、前端15项通过。主目录配对程序已备份更新，关闭旧窗口重开生效；安装包未更新。

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
