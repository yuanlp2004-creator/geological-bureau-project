# 历史硬件转角记录与样品转存

历史转角记录由 `acquisition` 模块提供。现行样品逐角摄谱、基线和峰位监测、有限重采及人工接管由样品摄谱工作台处理。 [样品采集导读](12_样品采集_acquisition.md) · [S14 验收](../acceptance-reports/S14/验收报告.md)

## 兼容接口

- `GET /api/v1/hardware-acquisitions/options` 查询历史参数选项。
- `GET /api/v1/hardware-acquisitions/tasks` 查询任务列表。
- `GET /api/v1/hardware-acquisitions/tasks/{task_id}` 查询任务及原始证据摘要。
- `GET /api/v1/hardware-acquisitions/tasks/{task_id}/frames`、`/traces`、`/decisions` 查询帧、通信轨迹及决策。任务详情与帧接口支持 `include_points=true`。
- `POST /api/v1/hardware-acquisitions/tasks/{task_id}/analysis-sample` 将已确认结果转存为正式样品。调用方同时需要 `hardware-acquisition.execute` 和 `acquisition.write`。

历史 GET 需要 `hardware-acquisition.read`。独立任务创建返回 405，旧执行及控制路径返回 404。 [API 路由](../../app/backend/api/hardware_acquisition.py)

## 数据保留与验证

历史服务读取 `hardware_tasks`、计划、原始帧、区间结果、轨迹和决策。转存校验方法版本、确认帧及其哈希，沿用来源标识防止重复导入。样品及 `hardware.sample.save` 审计在同一事务提交。 [历史服务](../../app/backend/modules/acquisition/legacy_hardware.py) · [恢复演练](../../app/tests/test_legacy_read_parity.py) · [分析及报告](../../app/tests/test_legacy_d05_contract.py)
