# GeoSpectrum

以 **SpecDirect 2.0.2 自动转角光谱仪分析软件** 的业务和旧格式为研究对象，使用 **FastAPI + React/TypeScript + SQLite + Tauri 2** 实现的 Windows 桌面光谱分析项目。

项目覆盖方法与分析谱线管理、旧数据只读迁移、谱图查看、设备与模拟采集、定量分析、标准曲线、后处理以及报告导出。当前用于开发和内部验证；真实转角/汞灯设备验收、代码签名和干净 Windows 环境安装升级验证仍有外部依赖，具体状态以验收报告为准。

## 仓库内容

```text
.
├─ README.md             项目介绍与开发入口
├─ PLAN.md               总体计划、业务范围和验收门禁
├─ AGENTS.md             项目协作与 AI 执行规则
├─ app/
│  ├─ backend/           FastAPI、业务模块、SQLite 迁移与运行资源
│  ├─ frontend/          React/TypeScript 页面、组件与 API 客户端
│  ├─ src-tauri/         Windows 桌面壳与本机能力
│  ├─ tests/             自动化测试
│  └─ tools/             构建、迁移、检查与开发工具
└─ docs/                 设计、代码导读、使用说明与验收记录
```

仓库提交正式源码、依赖清单/锁文件、必要资源和文档。旧 Delphi 工程、旧版运行目录、`SpecFile/`、`UI测试/`、独立重建工程、本机 EXE、安装包、依赖目录、缓存和运行数据库不包含在当前版本中。文档中的部分历史链接指向这些本地资料，需要另行准备。

## 功能范围

- 用户、角色、权限、审计、软件设置与运行事件。
- 方法版本、采集条件、分析谱线、方法预览与打印。
- 旧方法、谱图和分析结果的只读解析、暂存校验及迁移。
- 设备适配、模拟采集、色散校准、样品队列与重复采集。
- 定量分析、重复质控、标准曲线、后处理与报告导出。

模拟器与自动化测试只能验证对应的软件路径，不能替代真实仪器验收。已有记录请查看 [验收报告索引](docs/acceptance-reports/README.md)；本次仓库整理不代表重新完成全部验收。

## Windows 开发运行

浏览器开发需要 Python 3.11+、Node.js 和 pnpm。前端依赖使用 `app/frontend/pnpm-lock.yaml`，桌面工具依赖使用 `app/package-lock.json`。桌面编译还需要 Rust/MSVC Build Tools 与 WebView2；旧 Access 读取器另有 .NET/Jet 要求，详见 [应用开发说明](app/README.md)。

以下命令在 PowerShell 中执行。

### 1. 获取代码并安装依赖

```powershell
git clone https://github.com/yuanlp2004-creator/geological-bureau-project.git
cd geological-bureau-project
cd app
python -m venv .local\build-venv
.\.local\build-venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd ci
npx.cmd --yes pnpm@11.19.0 --dir frontend install --frozen-lockfile
```

### 2. 启动后端

在 `app` 目录执行：

```powershell
$env:SPECTRUM_DATA_DIR = "$PWD\.local\runtime\dev"
.\.local\build-venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8787
```

后端启动时初始化并迁移 SQLite。上述配置将开发数据放入已忽略的 `app/.local/runtime/dev/`；未设置时，Windows 默认使用 `%LOCALAPPDATA%\cn.geospectrum.desktop`。

### 3. 启动前端

另开一个终端，进入本仓库的 `app` 目录后执行：

```powershell
npm.cmd run frontend:dev
```

打开 <http://127.0.0.1:5173>，按页面提示完成首次管理员设置。后端 API 文档位于 <http://127.0.0.1:8787/docs>。

### 4. 常用检查

在 `app` 目录执行：

```powershell
.\.local\build-venv\Scripts\python.exe -m pytest -q
npm.cmd run frontend:build
```

依赖旧版原始资料的测试需要自行准备相应本地资料；只克隆此源码仓库不能保证这些兼容性测试全部运行。浏览器集成测试还需要 Playwright，配置与桌面打包步骤见 [app/README.md](app/README.md)。

## 阅读入口

- [项目阅读指南](docs/项目阅读指南.md)：从前端、接口、业务服务到数据库追踪功能。
- [文档索引](docs/README.md)：代码导读、研究资料、设计与发布记录。
- [离线使用手册](docs/使用与说明/GeoSpectrum_使用手册.html)：克隆后用浏览器打开。
- [总体计划](PLAN.md)：实施范围、步骤和验收要求。
- [应用开发说明](app/README.md)：源码组织、测试工具与 Windows 构建。
- [验收报告索引](docs/acceptance-reports/README.md)：自动化结果、人工验收和外部依赖。

源码、验收记录与本机生成的 EXE 可能属于不同快照，请按对应报告和发布清单核对。当前仓库不分发可直接运行的安装包。
