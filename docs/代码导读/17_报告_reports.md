# 报告模块导读（`reports`）

## 1. 模块定位

本模块把一个或多个已完成分析运行的最终合并结果固化为版本化报告模型，然后提供确认、预览、导出和打印。报告保存的是创建时快照，不是每次打开时重新拼接当前业务数据。

## 2. 代码入口

- 服务：[`modules/reports.py`](../../app/backend/modules/reports.py)
- 打印边界：[`printing/__init__.py`](../../app/backend/printing/__init__.py)，报告直接使用公共打印适配，不再依赖方法打印服务。
- API：[`api/reports.py`](../../app/backend/api/reports.py)；`/api/v1/reports`
- 请求模型：[`schemas/reports.py`](../../app/backend/schemas/reports.py)。
- 前端：`App.tsx` 中的 `ReportsPage`
- 测试：[`tests/test_s19_reports.py`](../../app/tests/test_s19_reports.py)

## 3. 报告模型构建

`_build_model()` 是核心聚合点：

1. 检查分析运行已经完成。
2. 要求存在最终合并结果，而不仅是原始强度。
3. 收集样品、元素、方法版本、计算配置、QC 快照和曲线快照。
4. 根据过滤条件选择行列。
5. 按 `standard` 或 `exchange` 排列生成稳定模型。

模型和 SHA-256 一起写入报告记录。后续业务数据变化不应悄悄改变旧报告内容。

## 4. 创建与确认

`create()` 选择模板、运行、排列和过滤条件，生成报告编号、版本、模型和草稿状态。`confirm()` 将草稿变为确认状态，并记录操作者和时间。

确认不是重新计算。若输入事实需要变化，应创建新报告版本，而不是修改已确认报告的模型。

## 5. 表格、预览与导出

`_headers()` 和 `_table()` 从同一报告模型产生二维表。`_encode_table()` 支持 TXT、CSV、Excel；`_pdf()` 产生 PDF。`preview()` 生成浏览器预览，`export()` 负责文件或打印输出。

`_atomic()` 使用临时文件加原子替换，并处理同名策略。打印机列表和打印动作经统一打印服务完成，不能由页面直接访问系统打印机。

每次导出保存格式、路径或打印信息、内容哈希和结果状态，便于复核“某份报告当时输出了什么”。

## 6. 核心数据

- `report_templates`：可用模板定义。
- `reports`：编号、版本、状态、不可变模型与哈希。
- `report_exports`：文件导出和打印记录。
- 分析运行、QC、曲线和最终合并结果只作为创建时输入。

## 7. 推荐阅读顺序

`templates()` → `_build_model()` → `create()` → `confirm()` → `_headers()` / `_table()` → `_encode_table()` / `_pdf()` → `_atomic()` → `export()` → `preview()`。

## 8. 修改检查

- 是否只接受已完成且存在最终合并结果的分析运行。
- 报告是否固定方法、QC、曲线和计算配置版本。
- 标准/交换排列是否同时正确调整行列语义。
- 已确认报告是否保持不可变。
- 预览、TXT、CSV、Excel、PDF 是否来自同一模型。
- 原子写和同名策略是否安全，打印是否完整留痕。
- 运行 S19 测试，并人工检查一份中文 PDF/预览。
