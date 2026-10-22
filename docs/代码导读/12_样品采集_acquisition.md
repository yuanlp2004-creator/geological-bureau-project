# 蒸发与样品摄谱模块导读（`acquisition`）

## 1. 模块定位

本采集领域包含两个业务子模块：蒸发摄谱研究完整时间序列与有效区间；样品摄谱按方法采集样品，管理队列与重复测量。两者有独立入口、表单与任务列表，共用 CCD 采集状态机、设备适配、帧保存和安全收尾。当前采集事件由确定性模拟数据产生，重点验证旧计算口径、任务状态、持久化和失败收尾。

## 2. 代码入口

- 服务：[`modules/acquisition/service.py`](../../app/backend/modules/acquisition/service.py)
- 设备模拟：[`modules/devices/service.py`](../../app/backend/modules/devices/service.py)
- 队列关联：[`modules/sample_queues.py`](../../app/backend/modules/sample_queues.py)
- API：[`api/acquisition.py`](../../app/backend/api/acquisition.py)；`/api/v1/acquisitions`
- 请求模型：[`schemas/acquisition.py`](../../app/backend/schemas/acquisition.py)。
- 前端：[`SampleAcquisitionPage.tsx`](../../app/frontend/src/pages/acquisition/SampleAcquisitionPage.tsx)
- 蒸发入口：[`EvaporationAcquisitionPage.tsx`](../../app/frontend/src/pages/acquisition/EvaporationAcquisitionPage.tsx)；共用工作区：[`AcquisitionWorkspace.tsx`](../../app/frontend/src/pages/acquisition/AcquisitionWorkspace.tsx)。
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

任务类型分为蒸发实验和样品；蒸发实验固定单次全时保存，样品支持平均谱与完整区间帧。样品页面绑定已发布方法版本和可选队列项；创建时固化设备配置、CCD 布局和相关条件，避免运行中配置漂移。

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

## 实现分工

`SampleAcquisitionPage` 与 `EvaporationAcquisitionPage` 固定各自任务类型，组合独立业务表单。`AcquisitionConditionFields` 共用设备和时间字段；`AcquisitionWorkspace` 共用控制、请求归属保护、监控、谱图与消息。即时定量和异常样品处置仅在样品页显示。

`GET /api/v1/acquisitions/tasks?task_kind=sample|evaporation` 在分页之前筛选类型，省略参数保留原混合列表。已有任务仍在原表中，无需迁移或重建；两个入口共用既有采集权限和当前方法门禁。

`acquisition/service.py` 保留 start/step/pause/resume/stop/fail/close、重复推进以及任务锁和适配器字典；`repository.py::AcquisitionRepository` 拥有任务/样品查询与装配、创建、帧存储、完成结果、区间及命名。存储方法继续接收控制流程持有的原连接，不独立提交外层事务。`simulation.py::_seeded_acquisition_event` 生成确定性模拟帧，`codec.py` 保留 uint16/float32 编解码与 average_points。公开 `get_task` 供 API 查询，路由不再调用私有 `_task_dict`。前端 `SampleAcquisitionForm/Monitor/Results` 从父页接收状态与回调；自动推进计时器现由共用的 `AcquisitionWorkspace` 管理。

`acquisition_import.py`在已有连接内导入采集任务、样品、谱带及帧；后处理转换工作单元统一提交或回滚，导入能力不独立提交。

## 当前条件、曝光与队列操作（2026-10-16）

方法保存时，各转角的存储范围取1至总采集帧数；逐线计算区间在分析谱线顶部维护。区间曝光开启后保留全时数据供逐线计算，已发布旧版本继续按其原载荷解释。样品摄谱默认继承方法，手动覆盖位于高级采集设置。

蒸发摄谱可独立“保存激发条件”，与色散默认值分开；“软件设置 → 分析参数”的空白传输时间用于方法采样周期编辑时重算空白次数，已有方法未编辑时保持原值。当前预录样品全部重复完成后，前端自动带出下一项和重复数，仍由操作员开始下一项。下游谱图与分析可读取完整原始积分及选线曝光观察，结果快照不回写。验证见 [十项实施清单](../acceptance-reports/S24/artifacts/2026-10-16-legacy-ten-completion/实施清单.md)。
