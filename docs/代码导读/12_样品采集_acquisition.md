# 样品采集模块导读（`acquisition`）

## 1. 模块定位

本模块执行蒸发台和样品的多阶段、多重复 CCD 采集，把原始帧聚合为样品波段，并可与样品队列关联。当前采集事件由确定性模拟数据产生，重点验证旧计算口径、任务状态、持久化和失败收尾。

## 2. 代码入口

- 服务：[`modules/acquisition.py`](../../app/backend/modules/acquisition.py)
- 设备模拟：[`modules/devices.py`](../../app/backend/modules/devices.py)
- 队列关联：[`modules/sample_queues.py`](../../app/backend/modules/sample_queues.py)
- API：[`api/acquisition.py`](../../app/backend/api/acquisition.py)；`/api/v1/acquisitions`
- 请求模型：[`schemas/acquisition.py`](../../app/backend/schemas/acquisition.py)。
- 前端：`App.tsx` 中的 `SampleAcquisitionPage`
- 测试：[`tests/test_s13_acquisition.py`](../../app/tests/test_s13_acquisition.py)

## 3. 任务状态机

```text
draft → countdown → pre_excitation → burn → dark
  → between_repeats → 下一重复的 countdown
  → completed

执行态 ↔ paused
执行态 → stopping → stopped
任意阶段异常 → failed
```

任务类型分为蒸发台和样品；存储策略分为仅保存平均谱与保存完整间隔帧。创建任务时固定当前已发布方法版本、设备配置、CCD 布局、重复次数和可选队列项，避免运行中配置漂移。

## 4. 确定性采集事件

`_seeded_acquisition_event()` 从捆绑 ACQ 事件派生当前任务、重复、阶段和帧的数据。它保留源传输哈希，再按稳定 seed 施加可复现变化，因此测试能区分“输入样本改变”和“派生规则改变”。

`_store_event()` 保存正常帧；`_store_damaged()` 保存故障证据。任务失败时 `_fail_task()` 负责状态、消息、审计和适配器收尾。

## 5. 旧版平均算法

`average_points()` 对每个像素计算：

```text
燃烧帧平均值 ÷ cycle - 暗电流帧平均值 ÷ cycle
```

最终结果设置下限 `LowAvg = 0.1`，对应旧版 `TCcdBand.CalAllAvgs` 的兼容口径。平均结果以 float32 存储；原始采集帧以 uint16 存储。改变数值类型、除法顺序或下限都会改变历史兼容结果。

## 6. 完成与关联

`_finalize_sample()` 生成每个 CCD 的平均波段，保存波段哈希，并按存储策略决定是否保留全部帧。重复完成后 `_begin_next_repeat()` 创建下一样品；最后一次完成时更新任务，并通过样品队列服务写入关联光谱哈希。

`rename()` 同步采集后名称与关联队列项；`mark_interval()` 标记可供后处理读取的区间；`analysis()` 和 `band()` 提供下游分析需要的结构。

## 7. 核心数据

- `acquisition_tasks`、`acquisition_samples`
- `acquisition_frames`、`acquisition_sample_bands`
- `acquisition_intervals`、`acquisition_messages`
- 与 `method_versions`、`device_profiles`、`ccd_layouts`、样品队列的版本化关联

## 8. 推荐阅读顺序

`AcquisitionState` → `_seeded_acquisition_event()` → `average_points()` → `create_task()` → `start()` → `step()` → `_finalize_sample()` → `_begin_next_repeat()` → `rename()` / `mark_interval()`。

## 9. 修改检查

- 任务是否在创建时固定方法、布局、配置和重复次数。
- 同一 seed、重复、阶段和帧是否仍可复现。
- 平均算法的 float32、cycle 和 `0.1` 下限是否保持兼容。
- 完整帧/仅平均两种存储策略是否真的不同。
- 失败、暂停和停止是否关闭适配器并保存消息。
- 队列关联、采集后重命名和区间标记是否在事务中一致。
- 运行 S13 测试和相关队列测试。

## 2026-09-14 已有采集记录导入边界

[`acquisition_import.py`](../../app/backend/modules/acquisition_import.py) 属于采集模块，提供已有帧记录的事务内导入。`ImportedAcquisition` / `ImportedBand` 描述输入，`AcquisitionRecordImporter.bind()` 绑定已有连接，`import_record()` 写入采集任务、样品、谱带和逐帧记录。它不创建 Database、不获得第二个写锁、不独立提交；后处理转换工作单元负责统一提交与回滚。原设备采集状态机及服务生命周期未修改。
