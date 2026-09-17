# 设备配置与模拟器模块导读（`devices`）

## 1. 模块定位

本模块管理设备配置，并提供基于捆绑 `.acq` 样本的确定性 CCD 调试模拟器。当前 `DeviceService` 使用的是 `AcqSimulatorAdapter`；配置里出现串口字段不代表这里已经实现真实串口采集。

真实转角协议在 `hardware-acquisition` 中仍受协议门禁约束，真实汞灯控制则属于 `mercury-calibration`。

## 2. 代码入口

- 服务与适配器：[`modules/devices.py`](../../app/backend/modules/devices.py)
- API：[`api/devices.py`](../../app/backend/api/devices.py)；`/api/v1/devices`
- 请求模型：[`schemas/devices.py`](../../app/backend/schemas/devices.py)。
- 前端：[`frontend/src/pages/devices/AcquisitionPage.tsx`](../../app/frontend/src/pages/devices/AcquisitionPage.tsx)
- 测试：[`tests/test_s11_devices.py`](../../app/tests/test_s11_devices.py)

## 3. 配置模型

`validate_profile()` 统一验证名称、传输方式、串口参数、屏幕坐标换算、镜像设置和超时等字段。`screen_conversion()` 把物理/显示参数转换成稳定的坐标换算结果。

配置由 `DeviceService.profiles()`、`profile()`、`create_profile()` 和 `update_profile()` 管理。写操作同时记录审计；局部更新必须走同一验证器，不能绕过完整配置约束。

## 4. ACQ 模拟数据

`parse_acq_frame()` 解析固定结构的 `.acq` 样本。当前基础常量是每次事件 3 帧、每帧 2 个 CCD、每个 CCD 2048 点，并按选定帧索引提取预激发、燃烧和暗电流数据。

`_ccd_points()` 同时处理 CCD 选择和镜像方向。修改布局时要检查所有调用处，不能只改常量而遗漏帧偏移计算。

## 5. 适配器状态机

`DeviceAdapter` 协议定义：

- `connect()` / `disconnect()`
- `start_debug()`
- `step_debug()`
- `stop_debug()`

`AcqSimulatorAdapter` 实现固定状态迁移，并用 `seed` 保证重复运行可复现；`fault_frame` 用于稳定注入某一帧失败。每次调用返回 `DeviceEvent`，其中包含事件类型、状态、关联 ID、帧数据或错误信息。

`DeviceService` 持有当前适配器和连接配置，再将设备事件包装成 API 响应和审计记录。

## 6. 不能误读的边界

- 模拟器验证的是应用状态机、数据流和故障收尾，不证明真实硬件协议正确。
- 串口配置持久化不等于串口命令已经获证。
- `.acq` 捆绑样本是开发测试输入，不是 S14/S15 的现场验收证据。

## 7. 推荐阅读顺序

`validate_profile()` → `parse_acq_frame()` → `DeviceAdapter` → `AcqSimulatorAdapter` → `DeviceService.connect()` → `start_debug()` / `step_debug()` / `stop_debug()` → S11 测试。

## 8. 修改检查

- 配置创建和更新是否使用相同验证规则。
- ACQ 帧长度、CCD 数量、点数和镜像方向是否严格检查。
- 同一 seed 是否仍得到相同事件；故障帧是否可复现。
- 非法状态调用是否拒绝，而不是偷偷重置适配器。
- 停止、断开和异常是否留下可诊断事件与审计。
- 不得把模拟器通过描述成真实设备验收通过。
