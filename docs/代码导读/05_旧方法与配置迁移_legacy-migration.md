# 旧方法与配置迁移模块导读（`legacy-migration`）

## 1. 模块定位

本模块只读导入 SpecDirect 的 `DIRECT.MTD`、`DIRECT.CFG` 和 `DIRECT.OPT`，建立新版方法、布局、校准和来源映射。它不回写 Access，不修改旧文件，也不处理旧谱图或结果矩阵。

权限为 `migration.read/write`，依赖 `core`、`auth`、`methods`。

## 2. 代码入口

- 暂存与原子提交：[`legacy_migration/service.py`](../../app/backend/modules/legacy_migration/service.py)。
- 读取器探测与只读副本：[`legacy_migration/reader.py`](../../app/backend/modules/legacy_migration/reader.py)。
- 旧记录归一化：[`legacy_migration/normalization.py`](../../app/backend/modules/legacy_migration/normalization.py)；数值与 BLOB 解码：[`legacy_migration/records.py`](../../app/backend/modules/legacy_migration/records.py)。
- CFG/OPT：[`legacy_migration/configuration.py`](../../app/backend/modules/legacy_migration/configuration.py)；源指纹：[`legacy_migration/sources.py`](../../app/backend/modules/legacy_migration/sources.py)。
- 公开服务和消费者辅助函数由 legacy_migration/__init__.py 显式导出；错误位于 errors.py。
- 独立读取器：[`tools/legacy-mdb-reader/`](../../app/tools/legacy-mdb-reader/)
- 冻结资源回退脚本：`backend/resources/legacy_reader/read_access.ps1`
- API：[`api/legacy_migration.py`](../../app/backend/api/legacy_migration.py)；`/api/v1/legacy-migration/diagnostics|stage|runs|commit`
- 请求模型：[`schemas/legacy_migration.py`](../../app/backend/schemas/legacy_migration.py)。
- 前端：`pages/migration/LegacyMigrationPage.tsx`（相对于 frontend/src/）。
- 测试：[`tests/test_legacy_migration.py`](../../app/tests/test_legacy_migration.py)

## 3. 为什么需要独立读取器

旧 `.MTD` 是 Jet/Access 数据库，读取依赖 32 位 Jet 提供程序。主 FastAPI 进程保持普通 Python 架构，旧 Access 读取隔离到 .NET 8 `win-x86` 工具或 32 位 Windows PowerShell。

`_reader_candidates()` 的优先级：

1. `GEOSPECTRUM_LEGACY_READER` 显式路径。
2. 构建好的 .NET 读取器。
3. 系统 32 位 PowerShell 加打包读取脚本。

没有可用读取器时只禁用迁移入口，不阻止常规 API 启动。

## 4. 两阶段流程

### 暂存

`stage()`：

1. 校验三个源路径并记录大小、时间和 SHA-256。
2. 把 MTD 复制到系统临时目录后读取。
3. 校验读取器版本、必需表和 BLOB 长度/哈希。
4. 解析 CFG/OPT，支持 UTF-8 BOM 和 GB18030。
5. 规范化方法、条件、谱线、标准点、布局和校准。
6. 写入迁移运行与 staging，不写正式业务实体。

### 提交

`commit()`：

1. 再次检查三个源文件未变化。
2. 以来源组合指纹判断是否已经提交。
3. 在单一事务中创建业务实体和来源映射。
4. 写入实体映射、报告和审计。
5. 任一实体失败时整体回滚。

## 5. 旧值映射

- 旧线型数字映射为分析线、内标线和定位线。
- 峰值数字映射为最大单点或高斯。
- 拟合数字映射为直线、二次、三次或样条。
- 旧方法默认计算档案为 `legacy_2_0_2`。
- 16/50 点标准 BLOB 由 `_standard_blob()` 验证并转换。

未知表结构、未知 BLOB 长度、哈希不符或源文件在暂存后变化都会拒绝提交。

## 6. 数据表

- `legacy_import_runs`
- `legacy_import_staging`
- `legacy_import_entities`
- 目标 `methods/method_versions/ccd_layouts/dispersion_calibrations`

`resolve_method_id()` 是其他迁移模块解析旧方法 ID 的公开服务边界，优先使用它而不是直接查询映射表。

## 7. 推荐阅读顺序

`_source_snapshot()` → `_decode_ini()` → `_reader_candidates()` → `_read_access()` → `_normalize_access()` → `_fingerprint()` → `stage()` → `commit()` → `resolve_method_id()`。

## 8. 修改检查

- 原文件是否始终只读并保留指纹。
- 读取是否发生在临时副本。
- 新格式变体是否已有旧版源码/运行证据。
- 重复导入是否幂等。
- 失败是否不留下部分业务实体。
- 更新黄金样本、诊断、拒绝路径和迁移测试。
