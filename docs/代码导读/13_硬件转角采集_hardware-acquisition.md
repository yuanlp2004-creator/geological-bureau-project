# 硬件转角采集模块导读（`hardware-acquisition`）

## 1. 模块定位

本模块实现多角度采集的业务状态机、转角计划、异常判定、人工干预、安全停止和通信追踪。模拟器闭环已经可测试，但真实串口转角协议仍是外部门禁：`SerialTurnAdapter` 不会发送未经证实的命令字节。

## 2. 代码入口

- 服务：[`modules/hardware_acquisition.py`](../../app/backend/modules/hardware_acquisition.py)
- API：[`api/hardware_acquisition.py`](../../app/backend/api/hardware_acquisition.py)；`/api/v1/hardware-acquisitions`
- 请求模型：[`schemas/hardware_acquisition.py`](../../app/backend/schemas/hardware_acquisition.py)。
- 前端：`App.tsx` 中的 `HardwareAcquisitionPage`
- 测试：[`tests/test_s14_hardware_acquisition.py`](../../app/tests/test_s14_hardware_acquisition.py)
- 验收状态：[`acceptance-reports/S14/验收报告.md`](../acceptance-reports/S14/验收报告.md)

## 3. 两类适配器

`SimulatorTurnAdapter` 组合 CCD 模拟器，依次实现连接、预激发、转角、采集和关闭，适合验证应用逻辑。

`SerialTurnAdapter` 是明确的协议门禁。当真实协议尚未取得时，它应返回 `deferred_external` 或明确错误，而不是猜测串口报文。读到该类时，不要把“类名存在”误解为真实硬件已经支持。

## 4. 任务状态机

主要状态包括：

```text
draft → connecting → connected → pre_excitation
  → turning → collecting → 下一角度或 completed

执行态 ↔ paused
异常 → anomaly → manual_intervention → 重试/接受/安全停止
外部条件不足 → deferred_external
严重失败 → safety_stopped / failed
用户停止 → stopping → stopped
```

`_control_scope()` 为每个任务提供非阻塞控制锁，防止同一任务被两个并发请求同时推进。公开的 `start()`、`step()`、`pause()`、`resume()`、`intervene()`、`stop()` 都在锁内调用私有实现。

## 5. 转角计划与异常

`_normalize_plan()` 将角度输入按 `short_to_long` 或 `key_first` 策略展开为固定步骤。任务创建后，计划步骤应被视为执行快照。

`_thresholds()` 规范化基线过低、过高、漂移、峰位偏移和超时等阈值。`_metrics()` 从帧计算观测指标，`_simulated_anomalies()` 提供确定性故障注入。异常策略支持有限重试后停止，或转入人工干预；重试次数必须有上限。

## 6. 证据与安全收尾

- `_trace()` 保存请求/响应方向、命令名称、载荷、关联 ID 和安全状态。
- `_store_frames()` 保存点数据、指标、哈希、异常和是否确认。
- `_decision()` 保存自动或人工决策及理由。
- `_safe_stop_db()` 在数据库内记录安全停止状态和消息。
- `_close_adapter()` 尽力释放设备上下文。

通信追踪应避免记录密钥等敏感内容；但设备动作、响应、关联 ID 和最终安全状态不能缺失。

## 7. 推荐阅读顺序

`HardwareTaskState` → 两个适配器 → `_control_scope()` → `_normalize_plan()` → `create_task()` → `_start()` → `_step()` → `_metrics()` → `_decision()` → `_safe_stop_db()`。

## 8. 修改检查

- 是否保持单任务并发互斥与有限状态迁移。
- 角度策略、关键角度和步骤序号是否可复现。
- 异常重试是否有硬上限，人工决定是否完整留痕。
- 任意失败路径是否尝试关闭设备并记录安全状态。
- 串口协议未知时是否继续拒绝发送猜测报文。
- 运行 S14 自动化测试；真实硬件验收仍需外部协议、设备和现场证据。
