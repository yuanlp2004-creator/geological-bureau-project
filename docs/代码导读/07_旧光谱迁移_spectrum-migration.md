# 旧光谱迁移模块导读（`spectrum-migration`）

## 1. 模块定位

本模块把旧版 Access 光谱文件中的 CCD 波段、平均值、原始帧和点火信息分阶段导入 SQLite。当前识别 `CDT`、`CMT`、`EDT`、`WDT` 四类格式。

它遵循“只读旧文件”的约束：先快照和解析，再提交规范化结果，不修复或回写源文件。

## 2. 代码入口

- 服务：[`modules/spectrum_migration.py`](../../app/backend/modules/spectrum_migration.py)
- 旧库读取边界：[`resources/legacy_reader/read_access.ps1`](../../app/backend/resources/legacy_reader/read_access.ps1)
- API：[`api/spectrum_migration.py`](../../app/backend/api/spectrum_migration.py)；`/api/v1/migrations/spectra`
- 请求模型：[`schemas/spectrum_migration.py`](../../app/backend/schemas/spectrum_migration.py)。
- 后续读取方：[`spectrum_viewer.py`](../../app/backend/modules/spectrum_viewer.py)、[`postprocessing.py`](../../app/backend/modules/postprocessing/service.py)
- 测试：[`tests/test_s08_spectrum_migration.py`](../../app/tests/test_s08_spectrum_migration.py)

## 3. 主流程

```text
stage(path)
  → 记录源文件路径、大小、时间和 SHA-256
  → 在临时副本上调用旧 Access 读取器
  → _normalize() 校验并转成统一暂存结构
  → 保存迁移运行和暂存 JSON

commit(run_id)
  → 再次核对源文件快照
  → 写入正式光谱记录与波段
  → 标记迁移运行已提交
```

`stage()` 和 `commit()` 分离是本模块最重要的设计：解析成功不等于允许落入正式数据，提交前仍要确认源文件没有被替换。

## 4. 解析重点

- `_tables()` 统一旧表名，避免大小写和读取器输出差异扩散到业务代码。
- `_layout()` 要求存在 `CCD_BAND` 和 `LAYOUT`，并检查 CCD 数量、索引及点数。
- `_ignition()` 整理点火参数，同时记录信息是否完整。
- `_samples()` 按小端序解释浮点或无符号 16 位整数 BLOB，检查长度、有限数值和 SHA-256。
- `_bad_frames()` 保留坏帧位置及原因，不把损坏帧静默当成正常数据。
- `_stage_streaming()` 处理读取器返回 `blob_file` 的大字段，避免大 BLOB 必须一次性塞进进程间 JSON。

常见旧字段中，`CcdGapPoints`、`WsCof`、`CcdAvgs` 按浮点数组理解；`BurnAdcs`、`DarkAdcs` 按 16 位整数帧理解。修改这些规则前必须回到旧源码和原始样本核对。

## 5. 数据结果

迁移运行记录保存源快照、诊断、暂存内容、状态和提交时间；正式结果进入光谱记录及 `spectrum_bands`。每个波段保留布局、平均点、原始帧、坏帧和内容哈希，供查看器与后处理继续使用。

同一源哈希重复执行时应得到可识别的幂等结果，而不是无提示地产生多份业务数据。

## 6. 推荐阅读顺序

`diagnostics()` → `_read_access()` → `_normalize()` → `_samples()` → `_stage_streaming()` → `stage()` → `commit()` → `spectrum_viewer.py` 的 `_raw()`。

## 7. 修改检查

- 是否仍只读源文件，并在暂存和提交两处保留完整快照。
- BLOB 字节序、元素宽度、点数和哈希检查是否一致。
- 缺表、截断 BLOB、非有限数值、坏帧是否明确失败或被标记。
- 大 BLOB 流式路径与普通内存路径是否得到同一规范化结果。
- 重复暂存、重复提交是否幂等。
- 运行 S08 迁移测试，并用原始样本回归关键格式。
