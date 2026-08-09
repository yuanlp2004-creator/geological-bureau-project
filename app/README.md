# GeoSpectrum

SpecDirect 2.0.2 的新架构实现。`app/` 是正式实现目录；`Spec Source/`、`Spec2.02/`、`SpecFile/` 和 `UI测试/` 仍然是只读资料或视觉参考。

## 已完成范围（S01–S07）

- FastAPI 本地服务：健康检查、关于/诊断、能力清单、软件设置、运行事件。
- SQLite：WAL、外键、版本化迁移，保存元数据、设置和运行事件。
- React/TypeScript：六域导航、工作台、消息面板、设置页、关于/诊断页。
- Tauri 2：单实例插件、sidecar 生命周期入口和受控文件/目录对话框入口。
- 架构工具：模块清单生成器和依赖/注册约束测试。
- 本地身份：首次管理员、Argon2id 密码、角色权限、进程内会话、用户/角色管理和审计。
- 方法与条件：不可变版本、草稿/发布、当前方法、新建/复制/重命名/启停/软删除、CCD/色散和采集/质控/转角条件。
- 分析谱线：基线/分析/内标/定位四类谱线、CCD/转角可检测判定、引用与三种内标、峰值/拟合/单位/超限参数、标准点和关键波段优先级。
- 方法预览与打印：持久化打印机/纸张/方向/边距/版式参数，统一分页模型生成 HTML 预览和可检索文字 PDF，并提供系统打印与可自动验收的内置 PDF 虚拟打印机；失败任务保留渲染输入和错误 PDF。
- 旧版迁移：32 位 Jet 4.0 读取器只打开操作系统临时副本；FastAPI 提供暂存、字段/BLOB/引用校验、单事务提交、幂等指纹和迁移报告，导入 `DIRECT.MTD/CFG/OPT`，不导入旧样品与分析结果。

设备、样品、采集、实际曲线拟合/样品分析和分析结果报告属于后续步骤，导航中会明确显示为未启用。

旧方法读取器的 .NET 8 `win-x86` 工程和开发环境的 32 位 Windows PowerShell 回退实现位于 `tools/legacy-mdb-reader/`。没有 32 位 Jet 时仅迁移入口不可用，FastAPI 常规启动不受影响。

## 本地运行

后端需要 Python 3.11+：

```powershell
cd app
& 'C:\Users\Hust\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pip install -r backend/requirements.txt
& 'C:\Users\Hust\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8787
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
& 'C:\Users\Hust\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q
& 'C:\Users\Hust\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m coverage run --source=backend -m pytest -q
& 'C:\Users\Hust\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m coverage report -m
& 'C:\Users\Hust\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tools/generate_manifest.py
& 'C:\Users\Hust\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tools/build_sidecar.py
& 'C:\Users\Hust\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tools/verify_sidecar.py
& 'C:\Users\Hust\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tools/measure_tauri_startup.py
npm.cmd run tauri:build
```
