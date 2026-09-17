# 样品队列模块导读（`sample-queues`）

## 1. 模块定位

本模块负责采集前样号预录、重复次数、采集后重命名、`.sam` 导入导出，以及队列项与采集结果的关联。它不执行 CCD 采集。

权限为 `samples.read/write`，依赖 `core` 和 `auth`。导航要求存在可用当前方法。

## 2. 代码入口

- 服务：[`modules/sample_queues.py`](../../app/backend/modules/sample_queues.py)
- API：[`api/sample_queues.py`](../../app/backend/api/sample_queues.py)；`/api/v1/sample-queues`
- 请求模型：[`schemas/sample_queues.py`](../../app/backend/schemas/sample_queues.py)。
- 前端：`pages/sampleQueues/SampleQueuePage.tsx`（相对于 frontend/src/）。
- 测试：[`tests/test_sample_queues.py`](../../app/tests/test_sample_queues.py)、`test_s13_acquisition.py`

## 3. 名称与标准样

`normalize_name()` 统一去除空白、限制旧版名称字节宽度并处理非法值。`OLD_STANDARDS` 把 `S0–S9`、`SA–SF` 映射为旧版标准样索引。

队列项保存：

- `source_name`：导入时的原始名称。
- `pre_name`：采集前名称。
- `post_name`：采集后确认名称。
- `repeats`：需要执行的重复次数。
- `expanded_bands`：展开后的采集计数信息。
- `spectrum_hash`：关联完成后的采集结果指纹。

界面显示和创建采集任务时必须使用同一重复次数，不能一个显示队列值、另一个提交局部表单值。

## 4. 队列生命周期

```text
create/import → draft 队列
  → update/delete/clear 调整队列项
  → acquisition.attach_acquisition 关联采集结果
  → rename_linked_item 同步采集后名称
  → 全部队列项具备 spectrum_hash 后更新队列状态
```

`attach_acquisition()` 和 `rename_linked_item()` 接受已有数据库连接，用于让采集模块在同一事务中同时修改采集记录和队列状态。

## 5. SAM 导入导出

`import_bytes()`：

1. 对原始字节计算 SHA-256。
2. 按旧版文本规则解析样号。
3. 以源哈希保证同一文件重复导入幂等。
4. 对同名草稿队列执行受控合并或复用。

`export_sam()` 生成确定性文本并返回内容哈希。API 层记录导出审计，前端经统一 `saveFile()` 保存。

## 6. 数据表

- `sample_queues`
- `sample_queue_items`
- `audit_events`

位置通过 `position` 和 `_renumber()` 保持连续。删除项目后应重新编号，而不是留下依赖数据库 ID 的显示顺序。

## 7. 推荐阅读顺序

名称规范化函数 → `_validate_items()` → `create()` → `_replace_items()` → `import_bytes()` → `export_sam()` → `attach_acquisition()` → `rename_linked_item()`。

## 8. 修改检查

- 样号长度和编码是否仍兼容旧版。
- 重复次数是否在队列、页面和采集任务间一致。
- SAM 重复导入是否幂等。
- 采集后重命名是否同步队列和采集样品。
- 删除/清空是否拒绝破坏已关联数据的情况。
- 运行队列和 S13 采集测试。
