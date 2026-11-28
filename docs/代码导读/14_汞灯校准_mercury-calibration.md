# 历史汞灯会话与对中

历史汞灯校准会话由 `devices` 模块读取。现行现场操作在「设备调试 → 调试对中」中切换工作转角、观察三路 CCD，汞灯随仪器自动开启。现场验收仍需逐角核对汞谱与停止。 [设备导读](10_设备配置与模拟器_devices.md) · [S15 验收](../acceptance-reports/S15/验收报告.md)

## 兼容接口

- `GET /api/v1/mercury-calibrations/options` 查询历史谱线、设备、布局与活跃校准版本。
- `GET /api/v1/mercury-calibrations/sessions` 查询会话列表。
- `GET /api/v1/mercury-calibrations/sessions/{session_id}` 查询谱线、帧摘要、轨迹和版本关系。通过 `include_points=true` 请求原始点值。

GET 需要 `mercury-calibration.read`。独立会话创建返回 405，旧执行、应用及回滚路径返回 404。 [API 路由](../../app/backend/api/mercury_calibration.py)

## 数据保留与验证

历史服务读取会话原始测量帧、候选版本、应用前版本和当前活跃版本。备份维护继续抽样校验 `mercury_frames` 的数据。 [历史服务](../../app/backend/modules/devices/legacy_mercury.py) · [接口测试](../../app/tests/test_s15_mercury_calibration.py) · [恢复演练](../../app/tests/test_legacy_read_parity.py)
