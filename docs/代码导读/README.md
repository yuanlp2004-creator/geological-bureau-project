# GeoSpectrum 代码导读索引

本目录用于帮助开发者从“知道文件在哪”进一步走到“理解模块为什么这样工作”。文档全部依据当前 `app/` 实现编写，描述实际代码，不把规划目标误写成已经存在的物理分层。

执行修改前仍须先读项目根目录的 [`AGENTS.md`](../../AGENTS.md)、[`PLAN.md`](../PLAN.md) 和 [`项目阅读指南.md`](../项目阅读指南.md)。本目录是代码导读，不替代事实来源、步骤门禁或验收报告。

## 推荐使用方式

`main.py` 只负责应用装配。阅读具体功能时使用下面的固定链路：

```text
模块导读
  → modules/manifest.py 中的模块清单
  → api/<module>.py 中对应 API 路由
  → modules/<module>.py 中的应用服务
  → migrations/ 中对应表、索引和不可变触发器（db.py 调度）
  → frontend/src/api/<business>.ts 中的类型与请求
  → 页面组件
  → 对应测试与验收报告
```

每份模块文档都回答六个问题：模块负责什么、从哪里进入、核心对象是什么、主流程怎样走、哪些约束不能破坏、修改后验证什么。

## 跨层导读

- [`19_前端架构.md`](19_前端架构.md)：React 状态、页面分派、API 适配、导航和通用组件。
- [`20_数据库与API装配.md`](20_数据库与API装配.md)：FastAPI 组合根、Pydantic 契约、SQLite 迁移、事务和错误边界。
- [`21_Tauri与发布链.md`](21_Tauri与发布链.md)：桌面启动、进程密钥、sidecar、数据库升级、文件保存和发布构建。

## 18 个正式模块

| 序号 | 清单键 | 导读 | 主要步骤 |
|---|---|---|---|
| 01 | `core` | [`01_运行基础_core.md`](01_运行基础_core.md) | S01 |
| 02 | `about-diagnostics` | [`02_关于与诊断_about-diagnostics.md`](02_关于与诊断_about-diagnostics.md) | S01、S20 |
| 03 | `auth` | [`03_身份与审计_auth.md`](03_身份与审计_auth.md) | S02 |
| 04 | `methods` | [`04_方法谱线与打印_methods.md`](04_方法谱线与打印_methods.md) | S03–S05 |
| 05 | `legacy-migration` | [`05_旧方法与配置迁移_legacy-migration.md`](05_旧方法与配置迁移_legacy-migration.md) | S06 |
| 06 | `sample-queues` | [`06_样品队列_sample-queues.md`](06_样品队列_sample-queues.md) | S07 |
| 07 | `spectrum-migration` | [`07_旧光谱迁移_spectrum-migration.md`](07_旧光谱迁移_spectrum-migration.md) | S08 |
| 08 | `result-migration` | [`08_旧结果迁移_result-migration.md`](08_旧结果迁移_result-migration.md) | S09 |
| 09 | `spectrum-viewer` | [`09_光谱查看_spectrum-viewer.md`](09_光谱查看_spectrum-viewer.md) | S10 |
| 10 | `devices` | [`10_设备配置与模拟器_devices.md`](10_设备配置与模拟器_devices.md) | S11 |
| 11 | `dispersion` | [`11_色散校准_dispersion.md`](11_色散校准_dispersion.md) | S12 |
| 12 | `acquisition` | [`12_样品采集_acquisition.md`](12_样品采集_acquisition.md) | S13 |
| 13 | `hardware-acquisition` | [`13_硬件转角采集_hardware-acquisition.md`](13_硬件转角采集_hardware-acquisition.md) | S14 |
| 14 | `mercury-calibration` | [`14_汞灯校准_mercury-calibration.md`](14_汞灯校准_mercury-calibration.md) | S15 |
| 15 | `analysis` | [`15_分析与标准曲线_analysis.md`](15_分析与标准曲线_analysis.md) | S16–S17 |
| 16 | `postprocessing` | [`16_后处理_postprocessing.md`](16_后处理_postprocessing.md) | S18 |
| 17 | `reports` | [`17_报告_reports.md`](17_报告_reports.md) | S19 |
| 18 | `maintenance` | [`18_维护与帮助_maintenance.md`](18_维护与帮助_maintenance.md) | S20 |

## 当前实现的物理边界

业务逻辑主要位于 `app/backend/modules/`，但以下内容仍集中维护：

- API 路由按业务位于 `backend/api/`，在 `api/__init__.py` 显式注册。
- 请求和响应模型按业务位于 `backend/schemas/`，包入口只做显式兼容导出。
- 数据库网关在 `backend/db.py`，结构、历史迁移和默认数据在 `backend/migrations/`。
- 前端类型与请求位于 `frontend/src/api/` 各业务文件，index.ts 仅组合兼容导出。
- 认证状态在 `frontend/src/App.tsx`，跨页状态在 `layout/WorkspaceApp.tsx`，页面在 `pages/`。

因此模块导读会区分“模块拥有的业务含义”和“当前集中装配的位置”。新增代码应保持模块边界，但不能假设现有代码已经完全拆成独立包。

## 文档维护规则

- 模块新增公开流程、状态、表或安全门禁时，同步更新对应导读。
- 只改界面文案或局部样式时，无须机械改写模块导读。
- 文档中的函数名、表名和枚举值属于定位锚点，重命名后必须同步更新。
- 旧版事实发生变化时，先更新证据和计划，再更新本目录的解释。
- 文档只能解释真实实现，不能用“预期”“以后会有”掩盖尚未实现的能力。
