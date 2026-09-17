# 旧结果迁移模块导读（`result-migration`）

## 1. 模块定位

本模块严格解析旧版二进制结果文件 `.dat` 和 `.pdt`，把样品、元素列和结果矩阵迁入 SQLite。它与旧光谱迁移不同：这里解析的是定长二进制结构，不经过 Access 读取器。

## 2. 代码入口

- 服务：[`modules/result_migration.py`](../../app/backend/modules/result_migration.py)
- API：[`api/result_migration.py`](../../app/backend/api/result_migration.py)；`/api/v1/migrations/results`
- 请求模型：[`schemas/result_migration.py`](../../app/backend/schemas/result_migration.py)。
- 后续读取方：[`spectrum_viewer.py`](../../app/backend/modules/spectrum_viewer.py)
- 测试：[`tests/test_s09_result_migration.py`](../../app/tests/test_s09_result_migration.py)

## 3. 文件识别与边界

解析器用文件头区分结构：

| 格式 | 文件头 | 说明 |
|---|---:|---|
| DAT | `0x0A64` | 常规结果矩阵 |
| PDT | `0x0A70` | PDT 结果 |
| PDT 扩展段 | `0x0A73` | 带扩展数据段的变体 |

样品名是 10 字节定长字段，元素名是 4 字节定长字段；样品、谱线和 PDT 波段数分别有硬上限。`_bounds()` 在分配和循环前检查计数，防止损坏文件诱发越界或巨量读取。

## 4. 主流程

```text
stage(path)
  → _snapshot() 固定源文件证据
  → 读取全部二进制内容
  → _parse() 严格按格式消费字节
  → 保存暂存模型和诊断

commit(run_id)
  → 再次核对源快照
  → 写入结果矩阵及其样品、列信息
  → 标记提交状态
```

`_parse()` 不允许尾部存在无法解释的剩余字节，也拒绝非有限浮点数和矩阵尺寸不一致。这样的“严格失败”是兼容性保护，不应改成猜测或自动修复。

## 5. 编码与时间

`_decode()` 依次处理旧中文编码和常见兼容编码，并返回采用的编码信息，便于诊断。`_time()` 按 Delphi `TDateTime` 规则，以 `1899-12-30` 为起点转换为 UTC 时间。

修改这里时要特别防止两个错误：把定长字段当作以零结尾的无限字符串，以及把旧日期浮点数当作 Unix 时间戳。

## 6. 业务关联

提交时会尽量关联现有方法版本；找不到映射时允许形成可追踪的孤立历史结果，而不是伪造方法关系。正式结果通过 `result_matrices` 供统一光谱查看器读取。

源 SHA-256 是幂等与追溯的核心键。相同内容即使来自不同路径，也应能识别为同一来源事实。

## 7. 推荐阅读顺序

`_snapshot()` → `_decode()` → `_bounds()` → `_parse()` → `_samples()` → `stage()` → `commit()` → `spectrum_viewer.py` 中结果矩阵分支。

## 8. 修改检查

- 文件头、字段宽度、最大计数和字节消费位置是否仍被严格验证。
- 中文名称解码失败时是否给出可定位的字段和偏移。
- Delphi 时间转换是否保持时区口径。
- 截断文件、尾部垃圾、NaN/Infinity 是否被拒绝。
- 方法无法映射时是否保留事实而不伪造关联。
- 重复暂存和提交是否幂等，并运行 S09 测试。
