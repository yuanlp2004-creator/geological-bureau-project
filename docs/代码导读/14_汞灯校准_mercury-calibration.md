# 汞灯校准模块导读（`mercury-calibration`）

## 1. 模块定位

本模块通过汞谱参考线检查并校正波长位置，保存不可变对齐版本，支持应用和回滚。当前模拟适配器生成合成汞谱，并不控制物理汞灯；真实串口控制仍受协议与现场硬件门禁约束。

## 2. 代码入口

- 服务：[`modules/mercury_calibration.py`](../../app/backend/modules/mercury_calibration.py)
- API：[`api/mercury_calibration.py`](../../app/backend/api/mercury_calibration.py)；`/api/v1/mercury-calibrations`
- 请求模型：[`schemas/mercury_calibration.py`](../../app/backend/schemas/mercury_calibration.py)。
- 前端：`App.tsx` 中的 `MercuryCalibrationPage`
- 测试：[`tests/test_s15_mercury_calibration.py`](../../app/tests/test_s15_mercury_calibration.py)
- 验收状态：[`acceptance-reports/S15/验收报告.md`](../acceptance-reports/S15/验收报告.md)

## 3. 适配器边界

`MercuryAdapter` 只规定启动、取帧和关闭三个动作。

`MercurySpectrumSimulatorAdapter` 根据布局、参考线、物理偏移、seed 和故障配置生成可复现的高斯峰。它验证的是谱线定位、校正计算和状态收尾，不验证灯开关时序。

`SerialMercuryAdapter` 在协议缺失时明确阻断。不得为了让界面“跑起来”而填入虚构命令。

## 4. 会话流程

```text
create_session → draft
start → stabilizing
step → 采集稳定帧
step → acquiring → 分析参考线 → ready
apply → applied
rollback → rolled_back

主动停止 → stopped
设备异常 → safe_off
外部协议不足 → deferred_external
```

`_control_scope()` 防止同一会话并发推进。`_safe_off()` 是重要失败边界：它关闭适配器，并把错误、追踪、消息和安全状态写回数据库。

## 5. 谱线定位与校正

创建会话时复制精选汞参考线，并根据 CCD 布局、当前活动偏移和波长计算预期像素。`_locate()` 只在预期位置附近搜索峰值，找不到时明确标记，而不是在全谱随便取最高峰。

`_analyze()` 汇总各参考线的观测偏移，生成建议校正。`apply()` 创建不可变对齐版本并切换活动版本；`rollback()` 也通过版本关系恢复，不改写历史版本内容。

## 6. 数据与证据

- 参考线、校准会话、会话谱线和采集帧。
- 对齐版本与当前活动对齐关系。
- 设备追踪、业务消息、审计事件。
- 帧点数组及内容哈希。

物理偏移、当前活动偏移、建议偏移是三个不同概念；模拟器的物理偏移只是测试输入，不能直接作为产品当前配置写入。

## 7. 推荐阅读顺序

`MercuryAdapter` → 两个适配器 → `_expected_position()` → `create_session()` → `start()` → `step()` → `_locate()` → `_analyze()` → `apply()` → `rollback()` → `_safe_off()`。

## 8. 修改检查

- 稳定、采集、就绪、应用和回滚状态是否严格区分。
- 峰位搜索是否限制在参考线的合理窗口内。
- 未找到谱线、帧损坏和设备失败是否留下明确状态。
- 对齐版本发布后是否不可变，活动版本切换是否可回滚。
- 安全关闭是否在异常和用户停止两类路径中执行。
- 运行 S15 自动化测试；真实汞灯验证仍需协议和现场硬件证据。
