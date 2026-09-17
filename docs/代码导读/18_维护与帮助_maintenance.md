# 维护与帮助模块导读（`maintenance`）

## 1. 模块定位

本模块提供运行状态、在线备份、备份验证、恢复演练、WAL 检查点、优化、空间回收、保留策略、日志/临时文件清理和内置帮助。原则是先验证再操作，并且恢复演练只针对隔离副本，不直接覆盖当前业务库。

## 2. 代码入口

- 服务：[`modules/maintenance.py`](../../app/backend/modules/maintenance.py)
- 数据库封装：[`db.py`](../../app/backend/db.py)
- API：[`api/maintenance.py`](../../app/backend/api/maintenance.py)；`/api/v1/maintenance` 和帮助相关路由
- 请求模型：[`schemas/maintenance.py`](../../app/backend/schemas/maintenance.py)。
- 前端：`App.tsx` 中的 `MaintenancePage`、`HelpPage`
- 测试：[`tests/test_s20_maintenance.py`](../../app/tests/test_s20_maintenance.py)

## 3. 完整性快照

`_snapshot()` 收集：

- SQLite `integrity_check` 和外键检查结果。
- 关键业务表实体数量。
- 代表性 BLOB 的长度和 SHA-256。
- 数据库模式与运行信息。

`_verify_path()` 在独立连接中检查指定数据库文件，并可与预期快照比较。备份验证不能只看“文件存在且大小大于零”。

## 4. 备份与恢复演练

`backup()` 使用 SQLite 在线备份 API，在应用运行时生成一致副本；它校验输出目录和文件名，计算备份 SHA-256，验证备份内容，再记录元数据和保留期限。

`restore_rehearsal()` 把备份复制到隔离临时位置，在副本上打开、检查模式、外键、实体计数和 BLOB 指纹。成功只说明“该备份可按当前程序读取”，不会自动替换当前数据库。

## 5. 数据库维护

- `checkpoint()` 执行受控 WAL 检查点，并限制模式参数。
- `optimize()` 执行 SQLite 优化操作。
- `reclaim()` 在操作前后保存业务快照，执行空间回收后重新验证。
- `retention()` 清理过期备份记录及受控文件。

任何维护动作失败都应保留当前数据库，不得以删除业务数据作为自动修复手段。

## 6. 文件清理边界

`cleanup_logs()` 只处理已配置的运行日志范围，`cleanup_temp()` 只处理正式临时目录。两者按保留天数筛选，并记录操作结果。

不要把这些函数扩展成对项目根目录、用户主目录或任意输入路径的递归清理。新增清理目标时必须先固定允许目录并验证解析后的绝对路径。

## 7. 内置帮助

`help_topics()` 支持按标题、关键词和内容搜索；`help_topic()` 按稳定 slug 读取主题；`help_topic_for_error()` 把稳定错误码映射到解释和处理建议。

错误帮助的价值依赖错误码稳定性。改业务错误码时，应同步核对帮助主题和前端错误入口。

## 8. 推荐阅读顺序

`_snapshot()` → `_verify_path()` → `status()` → `backup()` → `verify_backup()` → `restore_rehearsal()` → `checkpoint()` / `optimize()` / `reclaim()` → 两个清理函数 → 帮助查询函数。

## 9. 修改检查

- 在线备份是否使用 SQLite 备份 API并在完成后验证。
- 备份与恢复演练是否比较实体数量和关键 BLOB 哈希。
- 恢复演练是否只操作隔离副本。
- 空间回收前后业务快照是否一致。
- 清理函数是否被固定在允许目录和保留期限内。
- 帮助主题是否覆盖新增稳定错误码。
- 运行 S20 测试，并在临时目录验证备份文件流程。
