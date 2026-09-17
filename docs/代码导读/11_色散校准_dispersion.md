# 色散校准模块导读（`dispersion`）

## 1. 模块定位

本模块采集校准光谱、定位已知谱线、拟合像素到波长的多项式，并发布不可变校准版本。已发布版本可以绑定到具体方法版本，供后续采集和分析复现当时的坐标关系。

## 2. 代码入口

- 服务：[`modules/dispersion.py`](../../app/backend/modules/dispersion.py)
- 设备输入：[`modules/devices.py`](../../app/backend/modules/devices.py) 的 `AcqSimulatorAdapter`
- API：[`api/dispersion.py`](../../app/backend/api/dispersion.py)；`/api/v1/dispersion`
- 请求模型：[`schemas/dispersion.py`](../../app/backend/schemas/dispersion.py)。
- 前端：`App.tsx` 中的 `DispersionPage`
- 测试：[`tests/test_s12_dispersion.py`](../../app/tests/test_s12_dispersion.py)

## 3. 任务状态机

```text
draft → pre_excitation → burn → dark → completed
             ↕ paused
             → stopping → stopped
任意执行态 → failed
```

`start_task()` 建立适配器上下文，`step_task()` 每次只推进一个确定步骤，便于前端轮询和测试精确观察。暂停、恢复、停止都验证当前状态；不能靠直接更新状态字段跨越状态机。

## 4. 帧存储

`_pack_points()` 把 16 位整数点压缩后存储，同时保存点数和 SHA-256。`_unpack_points()` 读取时重新检查压缩方式、长度和哈希。

这意味着数据库中的帧不是“可信内存”：任何读取路径都要经过完整性检查。`frames()` 默认返回元数据，需要时再展开点数组。

## 5. 谱线定位与拟合

任务谱线可以新增、删除、单条定位、批量定位、左右移动、保存位置或恢复位置。预期像素由现有系数和 CCD 几何估算，实际位置则从采集曲线的邻域峰值中寻找。

`_fit_polynomial()` 构造正规方程，`_gaussian_solve()` 解系数；拟合阶数必须与有效谱线数量相容。`fit_calibration()` 生成不可变版本，`publish_calibration()` 才把版本设为可用。`bind_calibration()` 绑定的是校准版本与方法版本，不是可变草稿任务。

## 6. 核心数据

- `dispersion_tasks`：采集任务和状态。
- `dispersion_frames`：压缩帧及完整性证据。
- `dispersion_task_lines`：任务中的参考谱线与定位结果。
- `dispersion_calibration_versions`：拟合后不可变版本。
- `method_calibration_bindings`：方法版本使用哪个校准版本。

## 7. 推荐阅读顺序

`DispersionState` → `_pack_points()` / `_unpack_points()` → `create_task()` → `start_task()` → `_advance_once()` → `locate_line()` → `fit_calibration()` → `publish_calibration()` → `bind_calibration()`。

## 8. 修改检查

- 状态推进、暂停和停止是否保持有限且可恢复。
- 帧解压后点数和 SHA-256 是否必检。
- 移动谱线是否区分临时位置、保存位置和恢复位置。
- 拟合是否拒绝谱线不足、重复位置和非有限值。
- 发布后版本是否不可变，方法绑定是否指向确切版本。
- 运行 S12 测试，并回归前端谱线定位交互。
