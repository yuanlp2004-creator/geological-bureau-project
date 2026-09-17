# 方法、谱线与打印模块导读（`methods`）

## 1. 模块定位

清单中的 `methods` 实际覆盖三个紧密相关的服务：

- `MethodService`：方法生命周期、条件、版本和当前方法。
- `SpectralLineService`：分析谱线、内标、标准点和排序。
- `MethodPrintService`：方法参数预览、PDF 和打印任务。

对应步骤是 S03–S05。权限为 `methods.read/write`。

## 2. 代码入口

- [`methods/service.py`](../../app/backend/modules/methods/service.py)：方法创建、编辑、发布、复制的完整版本事务和兼容入口。
- [`methods/runtime.py`](../../app/backend/modules/methods/runtime.py)：当前方法打开、暂停、删除和状态查询。
- [`methods/validation.py`](../../app/backend/modules/methods/validation.py)：条件校验；[`methods/geometry.py`](../../app/backend/modules/methods/geometry.py)：CCD/波长换算。
- [`methods/repository.py`](../../app/backend/modules/methods/repository.py)：版本查询、序号、选项与事务内审计。
- [`methods/values.py`](../../app/backend/modules/methods/values.py)：名称、默认条件、归一化和稳定序列化；错误在 methods/errors.py。
- [`methods/__init__.py`](../../app/backend/modules/methods/__init__.py)：原服务和消费者使用的显式导出。
- [`modules/spectral_lines.py`](../../app/backend/modules/spectral_lines.py)
- [`modules/method_printing/service.py`](../../app/backend/modules/method_printing/service.py)
- API：[`api/methods.py`](../../app/backend/api/methods.py) 的 `/api/v1/methods`、`/api/v1/spectral-lines`、`/api/v1/method-print`
- 请求/响应模型：[`schemas/methods.py`](../../app/backend/schemas/methods.py)，包含方法、谱线、方法打印模型。
- 前端：`pages/methods/MethodsPage.tsx、SpectralLinesPanel.tsx、MethodPrintPanel.tsx`（相对于 frontend/src/）。
- 测试：`test_methods.py`、`test_spectral_lines.py`、`test_method_printing.py`

## 3. 方法版本模型

`methods` 保存稳定身份和当前状态；`method_versions` 保存不可变版本载荷。方法状态为 `active/paused/deleted`，版本状态为 `draft/published`。

主要规则：

- 创建方法时建立首个草稿版本。
- 修改条件或谱线时生成新的草稿版本，不覆盖旧版本载荷。
- 发布前必须通过条件与谱线校验。
- 已参与采集或分析的发布版本不得原地修改。
- `method_runtime_state` 只记录当前方法、当前版本和动作状态。
- 删除是软删除；删除当前方法时清空当前引用。

方法名称按 GB18030 字节长度限制为 20 字节，并拒绝 Windows 文件名保留字符。这是旧版兼容口径，不是普通 Unicode 字符数限制。

## 4. 条件校验

`validate_conditions()` 交叉检查：

- CCD 布局和启用的色散校准。
- 波长范围和参考位置。
- 采样、预激发、燃烧、暗场与重复条件。
- 转角列表、存储模式和关键波段。
- 旧版/现代计算档案。

波长到 CCD 点位的换算依赖布局几何和色散系数。参考线落在 CCD 边缘漂移保护区时会被判为不可安全检测。

## 5. 谱线载荷

谱线不是独立数据库表，而是保存在方法版本 `payload_json` 中。`SpectralLineService` 每次变更都读取当前载荷、规范化谱线集合、写入新草稿版本并审计。

支持的线型包括：

- `baseline`
- `analysis`
- `internal_standard`
- `positioning`

固定参考基线 ID 为 `reference-baseline`。分析线可配置实际波长、扫描宽度、峰值模式、拟合方式、坐标方式、单位、超限参数、标准点和内标引用。

关键约束：谱线 ID 唯一、波长不能在容差内重复、引用不能成环、分析线数量不超过 300、标准点数量与值域合法。

## 6. 当前方法流程

```text
create/update → 草稿
  → publish → 发布版本
  → open → 设为当前方法
  → pause/resume → 同步方法状态与运行前置条件
  → acquisition/analysis 引用确切 method_version_id
```

前端导航是否可用依赖 `current()` 返回的状态，但真正创建采集或分析任务时仍会在后端再次校验。

## 7. 预览与打印

`MethodPrintService` 先用 `_snapshot()` 固定方法版本，再把条件和谱线转换为统一文档行，执行分页。HTML 预览和 PDF 渲染使用同一个分页模型。

打印有两种目标：

- 内置 `geospectrum-pdf` 虚拟打印机：把 PDF 保存到受控输出目录，适合自动验收。
- Windows 系统打印机：渲染临时 PDF 后调度系统打印。

每次打印创建 `method_print_jobs`，保存输入、页数、字段数、PDF 路径、状态和失败信息。失败不修改默认打印设置。

## 8. 数据表

- `methods`
- `method_versions`
- `method_runtime_state`
- `ccd_layouts`
- `dispersion_calibrations`
- `method_print_settings`
- `method_print_jobs`
- `audit_events`

## 9. 推荐阅读顺序

`DEFAULT_CONDITIONS` → `validate_method_name()` → `validate_conditions()` → `create/update/publish/open` → `canonical_lines()` → `SpectralLineService._commit()` → `MethodPrintService._snapshot()` → `_paginate()` → `render_pdf()` → `print_method()`。

## 10. 修改检查

- 是否仍通过新版本表达编辑。
- 条件、谱线、预览和采集引用是否是同一版本。
- `legacy_2_0_2` 与 `modern_v1` 是否明确保留。
- PDF 与 HTML 的字段和分页是否一致。
- 写操作是否记录审计。
- 运行三组方法相关测试和受影响的采集/分析测试。

## 2026-09-14 打印结构更新

`method_printing/service.py` 保留设置、方法快照、预览入口、打印任务及审计流程；`document.py` 组织文档行和分页；`rendering.py` 管理字体及 HTML/PDF 渲染。D1 已将打印机适配移到 [`backend/printing/`](../../app/backend/printing/__init__.py)，方法和报告共同调用 `SystemPrinters.printers()` 与公开的 `dispatch_pdf()`。原私有调度转发已移除；方法服务的 `printers()` 仍供方法 API 使用。

打印仍先保存 PDF 和渲染输入、登记任务，再调度打印机。调度失败保留文件并登记失败，不改默认设置。

## 2026-09-14 内部解耦更新

`Runtime.method_print_service()` 显式传入方法服务和公共打印适配。`methods/snapshots.py` 的公开快照读取绑定原事务，区分打印最新草稿、指定版本与分析已发布版本，消费者不获取 sqlite3.Row。`service.prepare()` 将原请求模型转为内部 `PrintSettings`；`document.py` 的行组织/分页只使用内部数据，不再导入请求模型或 ReportLab。`rendering.py` 继续负责字体和 HTML/PDF。HTTP 校验与默认设置保持。
