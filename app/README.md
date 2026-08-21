# GeoSpectrum

SpecDirect 2.0.2 的新架构实现。`app/` 是正式实现目录；`Spec Source/`、`Spec2.02/`、`SpecFile/` 和 `UI测试/` 仍然是只读资料或视觉参考。

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

## 本地运行

后端需要 Python 3.11+：

```powershell
cd app
$python = '.\.local\build-venv\Scripts\python.exe'
& $python -m pip install -r requirements.txt
& $python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8787
```

前端需要 Node.js：

```powershell
cd app
npm --prefix frontend install
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
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
