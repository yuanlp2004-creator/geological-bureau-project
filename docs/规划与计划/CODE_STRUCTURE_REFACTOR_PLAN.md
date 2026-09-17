# GeoSpectrum 代码结构重构计划

创建日期：2026-09-13；更新：2026-09-14。状态：`completed`。R0–R7 已完成，后端入口/API/模型、前端请求/页面和数据库迁移已按职责拆分，根目录程序与内部安装包已更新。正式发布仍受既有外部门禁约束。

本计划针对当前 `地质局/app/`，承接已完成的后端包目录简化，不涉及 `GeoSpectrum-rebuild`。治理依据为根目录 [PLAN.md](../../PLAN.md) 和 [AGENTS.md](../../AGENTS.md)。最初仅编制计划；用户随后要求“以你的计划开始重构”，当前实施记录见第 10 节。

## 1. 目标与命名决策

目标是让开发者能按“职责目录 → 具体业务”找到代码，同时减少入口文件承载的业务和反向依赖。以搬移已有完整函数、组件和类型为主，必要时调整依赖注入；不重新实现相同功能。

推荐采用上层职责目录，而不是把原文件名普遍变成前缀。

| 写法 | 判断 | 原因 |
|---|---|---|
| `main_methods.py`、`main_auth.py` | 不采用 | main 表示入口，不能说明文件是路由、业务服务还是模型；保留来源名称不能替代职责划分 |
| `main/methods.py` | 不采用 | 把所有入口中的代码放进 main 文件夹，仍然没有区分职责 |
| `api_methods.py`、`api_auth.py` | 小规模平铺可用，本项目不采用 | 已有较多业务模块，统一前缀会使根目录继续膨胀 |
| `api/methods.py`、`api/auth.py` | 后端采用 | api 表示 HTTP 接口边界，文件名表示业务对象 |
| `api/methods.ts`、`api/auth.ts` | 前端采用 | api 表示调用后端的客户端代码；与后端业务名对应 |
| `pages/MethodsPage.tsx` | 前端采用 | 路径说明是页面，组件名保留 Page，便于导入和搜索 |

命名规则：

- `main.py`、`main.tsx` 保留为实际启动入口；`App.tsx` 保留为前端应用装配入口。
- Python 业务文件使用 `snake_case.py`；React 组件使用 `PascalCase.tsx`；普通 TypeScript 业务文件沿用项目现有惯例，使用 `camelCase.ts`。跨语言保持业务词一致，例如 `sample_queues.py` 对应 `sampleQueues.ts`。
- 同一目录下不重复前缀：使用 `api/methods.py`，不使用 `api/api_methods.py`。
- `api` 在后端表示“接收请求”，在前端表示“发出请求”；通过 `backend/` 与 `frontend/src/` 区分。
- 不同时建立 `api/` 和 `routes/` 存放同一类后端路由；本计划统一选择 `api/`。
- 文件名按最终用途命名，不用 `part1`、`new`、`common2`、`misc`。已有小模块可以保持原状，不为统一外观强制增加层数。
- 同级不得同时保留 `api.ts` 和 `api/`，或 `schemas.py` 和 `schemas/`。迁移时在一个可运行批次内完成替换，避免解析歧义。

## 2. 已核实的现状与风险

以下行数是实施前的检查快照，不设最大行数验收指标；当前完成情况见第 10、11 节。

| 来源 | 当前职责与问题 | 拆分方向 |
|---|---|---|
| `backend/main.py`，2388 行 | 生命周期、全局服务、权限、中间件、路由、WebSocket，以及部分用户/角色 SQL | 保留入口；接口进入 `api/`；运行对象进入 `runtime.py`；已有业务服务继续在 `modules/` |
| `backend/auth.py` | 认证服务与 FastAPI 依赖混合；`require_session()` 反向导入 `.main.auth_service` | 认证服务保留；请求依赖移到 `api/dependencies.py` |
| `backend/schemas.py`，825 行 | 所有业务 Pydantic 模型集中 | 按接口业务拆成 `schemas/` 包，保持字段和验证规则 |
| `backend/db.py`，2020 行 | 连接、事务、基线建表、v11–v20 迁移集中 | 保留数据库网关；抽取迁移代码和初始化 schema |
| `frontend/src/App.tsx`，1725 行 | 启动、认证、导航、壳布局和多个完整页面集中 | 入口、壳组件、页面分别归位 |
| `frontend/src/api.ts`，1562 行 | 业务类型、请求方法、请求基础设施、Tauri 保存和目录选择集中 | `api/` 按业务分文件，`platform/` 放本机能力与浏览器回退 |
| `frontend/src/` | 已拆分页面与未拆页面并存；组件、页面、CSS 平铺 | `pages/`、`components/`、`layout/`、`styles/` 按实际归属整理 |

后端模块已存在 `modules/*.py`，本次不把每个模块机械拆成 domain/application/repository 四层。`AppService` 先保持用途；其依赖模型的导入随 schemas 调整，不同时进行额外业务重写。

上次目录简化报告记录：142 项 Python 测试通过、实际新入口启动通过、冻结后端业务验证通过。该记录是起点证据，不替代本计划实施时的重新验证。S14/S15/S21 的硬件、签名和干净 Windows 外部门禁继续保留。

## 3. 目标目录与职责

以下是目标示意，不是立即创建的文件清单。每个文件必须在有真实代码搬入时创建，省略号表示已有其他业务，不是空模块。

```text
app/
├─ backend/
│  ├─ main.py                    创建 FastAPI、生命周期、注册 API
│  ├─ runtime.py                 运行配置与共享服务对象的装配
│  ├─ auth.py                    认证、会话与密码服务
│  ├─ config.py
│  ├─ db.py                      连接、锁、事务和迁移调度
│  ├─ services.py                现有 AppService
│  ├─ upgrade.py                 数据库副本升级与切换
│  ├─ sidecar_entry.py            桌面后端入口
│  ├─ api/
│  │  ├─ __init__.py             明确的路由注册入口
│  │  ├─ dependencies.py         从当前应用获取服务、认证与权限依赖
│  │  ├─ middleware.py           进程密钥、CORS 等 HTTP 边界
│  │  ├─ errors.py               已确认语义相同的异常转换
│  │  ├─ system.py               健康、关于、诊断、设置与运行消息
│  │  ├─ auth.py                 登录、用户、角色、审计接口
│  │  ├─ methods.py              方法、条件、谱线与方法打印接口
│  │  ├─ events.py               WebSocket 与事件传输
│  │  └─ …                       其他已有业务接口
│  ├─ schemas/
│  │  ├─ __init__.py             无副作用；迁移阶段显式兼容导出
│  │  ├─ system.py
│  │  ├─ auth.py
│  │  ├─ methods.py
│  │  └─ …                       其他已有业务模型
│  ├─ migrations/
│  │  ├─ __init__.py             显式、有序迁移登记
│  │  ├─ baseline.py             原初始化 schema，原样搬移
│  │  ├─ defaults.py             原默认数据与不可变触发器
│  │  ├─ sql.py                  不隐式提交事务的 SQL 辅助函数
│  │  ├─ v11_devices.py
│  │  └─ …                       既有 v12–v20，版本和执行顺序不变
│  ├─ modules/                   保留现有业务服务
│  └─ resources/                 保留资源包与哈希清单
└─ frontend/src/
   ├─ main.tsx                   React 挂载入口
   ├─ App.tsx                    认证状态与应用装配
   ├─ navigation.ts              现有导航计算与门禁
   ├─ api/
   │  ├─ index.ts                兼容现有 api 对象及具名类型导出
   │  ├─ client.ts               请求、鉴权头、统一错误、基础 URL
   │  ├─ system.ts
   │  ├─ auth.ts
   │  ├─ methods.ts               方法请求及其类型
   │  ├─ events.ts                WebSocket URL 等事件客户端能力
   │  └─ …                       其余已有业务请求及类型
   ├─ platform/
   │  ├─ runtime.ts               Tauri 运行配置与浏览器适配
   │  └─ files.ts                 保存文件、选择旧目录及浏览器回退
   ├─ layout/                    WorkspaceApp、Sidebar、Header
   ├─ pages/                     页面及只属于该页面的组件/CSS
   │  ├─ methods/                MethodsPage、SpectralLinesPanel、MethodPrintPanel
   │  └─ …                       其他已有页面
   ├─ components/                真正跨页面复用的组件
   └─ styles/                    全局、主题和跨页面公共样式
```

`api/index.ts` 允许维护稳定导出和薄的 api 对象组合，不允许重新堆入请求实现。仅为兼容而存在的导出应写清楚用途；内部业务模块直接导入 `client.ts` 或所属业务类型，不反向导入 `index.ts`，防止循环。

## 4. 来源到目标的搬移清单

| 现有符号/代码 | 目标 | 搬移约束 |
|---|---|---|
| `main.py` 的 `database`、`service`、`auth_service`、事件订阅集合及服务获取函数 | `runtime.py` 和 `api/dependencies.py` | 单应用共享一套正确生命周期的对象；不在每次请求中新建认证会话库 |
| `auth.py` 的 `require_session`、`require_permission` | `api/dependencies.py` | 保留 401/403、错误码、权限判断和进程密钥边界；移除反向导入 main |
| `main.py` 路由装饰器及函数 | 对应 `api/*.py` 的 APIRouter | 保持路径、方法、响应模型、状态码、依赖、tags、OpenAPI operation ID 和事件顺序 |
| 用户/角色路由中的 SQL、事务及审计 | 现有 `AuthService` 的明确应用方法 | 以完整事务搬移，不改变回滚、权限、密码、审计或会话行为 |
| `_publish`、`event_subscribers`、`/ws/events` | 传输处理到 `api/events.py`，共享订阅状态到 runtime | 保留订阅隔离、认证及断开清理；业务服务不导入路由 |
| `schemas.py` 的请求/响应类型 | `schemas/<business>.py` | 先画引用关系，共享值模型只在确有多方引用时抽取；模块模型不依赖 API |
| `_migrate_v11` 至 `_migrate_v20` 和基线 SQL | `migrations/` | 原样迁移代码；不重新编号、不合并历史升级、不修改 SQL 语义 |
| `App.tsx` 的 `AuthForm`、`UsersPage`、`AuditPage` | `pages/auth/` | 保留登录、首次管理员、权限及错误恢复行为 |
| `WorkspaceApp`、`Sidebar`、`Header` | `layout/` | props 与状态所有权先保持原状，不顺便引入路由或状态库 |
| `MethodsPage`、`SpectralLinesPanel`、`MethodPrintPanel`、`lineToInput` | `pages/methods/` | 按完整组件和依赖搬移，保留当前三个方法导航入口 |
| `SettingsPage`、三种 MigrationPage、两种 SpectrumViewerPage、`SampleQueuePage`、`AboutPage` | `pages/` 内对应业务 | 先查可达性和调用者，不因名称含 Legacy 就删除旧视图 |
| 现有独立采集、色散、分析、报告、维护等页面 | `pages/` 内对应业务 | 后续批次只整理归属及相对导入，保留现有页面逻辑 |
| NumericInput、SpectrumPlot、TaskLayout、SimpleChartAxes 等 | `components/` 的实际共享归属 | 与依赖的模型、样式、测试路径一起调整；仅单页使用的组件留在所属页面 |
| `api.ts` 的 `requestRaw`、`request` | `api/client.ts` | 保留凭据、401 处理、错误结构、Blob 下载行为 |
| `desktopRuntime`、`saveFile`、`savePdfFile`、`selectLegacyDirectory` | `platform/` | 保留运行配置缓存、Tauri 调用和浏览器回退；不要求浏览器具备本机 API |
| `api.ts` 的各业务类型及 `api` 方法 | `api/<business>.ts` | 类型和请求先放一起，稳定以后再按实际需要细分 |

## 5. 关键依赖处理

### 后端运行对象

采用一个明确的运行容器，挂在当前 FastAPI 应用的 `app.state`，由请求依赖获取。`main.py` 负责装配，API 与认证服务不导入 main。测试通过应用工厂或依赖覆盖提供隔离容器，不能继续依靠修改已搬走的 `main.database` 来“看似隔离”。

保留 `backend.main:app` 启动入口。`sidecar_entry.py` 目前会在升级准备之后导入 main，并设置进程密钥；实施时必须同步调整设置位置，确保中间件读取同一个运行容器中的密钥。数据库仍在既有安全顺序中初始化，不在导入路由时初始化。

路由注册使用显式清单并与现有模块清单对应，复用已存在的模块登记机制；先检查 `ModuleManifest` 与 `ExtensionManifest` 的契约。不引入文件系统扫描自动注册，不为每个模块增加多处开关，测试扩展不得进入正式构建。

### 数据库与模型

继续只有一个连接/事务网关和原有迁移调度。`migrations/` 不导入 `db.py` 形成环；需要的连接对象通过参数传入。schemas 按真实引用拆分，避免经聚合导出相互导入。

### 前端组件与样式

组件拆出时先保持 props、状态和回调的原有位置；验证后才考虑单独提取 hook。先移动文件并维持 CSS 导入顺序，不同时重写选择器或主题变量。迁移后的静态源码测试要查实际文件，行为断言不能为适应拆分而删除或改为无效匹配。

## 6. 分批实施与停止点

只有用户后续明确授权才开始下列实施。每批完成并形成结果后停止，确认后再进入下一批；这些是 S01/S21 工程维护的内部批次，不新增产品功能步骤。

| 批次 | 最小可运行交付 | 核心验证与停止条件 |
|---|---|---|
| R0 基线 | 记录源码清单、现有未跟踪改动、接口快照、资源哈希和可恢复副本；不改行为 | 重新运行现有测试和前端构建，已存在失败单独登记；没有可恢复基线不开始搬移 |
| R1 运行对象与系统 API | runtime、请求依赖、进程密钥边界；迁出健康/关于/诊断等系统接口，其他路由仍可运行 | 正常启动、健康、认证成功/拒绝、隔离应用无共享会话；sidecar 密钥通过与错误密钥拒绝；不能有 API/auth 反向导入 main |
| R2 身份与方法 API | 登录/用户/角色/审计、方法/谱线/方法打印接口迁出；账户写事务进入服务；拆出对应 schemas | 401/403、用户角色事务与审计、方法保存/非法输入零写入、打印输出；接口快照一致 |
| R3 其余后端 API | 依次搬移队列与迁移、谱图、设备与采集、分析与报告、维护和 WebSocket；每组完成定向检查 | 迁移幂等及源哈希、采集停止收尾、分析黄金样本、报告输出、WebSocket 认证与断开；最终全量后端回归，入口只保留装配 |
| R4 前端请求层 | 将 api.ts 一次性替换为 api/，搬出 platform，保留导出兼容 | TypeScript/Vite 构建、登录及一个业务请求、401/错误提示、PDF/CSV 下载、目录选择取消及浏览器回退；无同级 api.ts 遗留 |
| R5 前端页面 | 先壳与登录，再方法页、迁移与谱图页、其他页；将已独立页面归位 | 每组构建并验证一条主流程和关键失败路径；方法导航、编辑保存、权限过滤、页面切换、明暗主题和窗口布局不退化 |
| R6 数据库整理 | 搬出历史迁移与基线 SQL，完成剩余 schemas 归属 | 空库初始化、受支持旧版本逐级升级、失败回滚、业务数据与版本保持、完整性与外键检查；不创建新的数据库业务版本 |
| R7 整体验证与交付 | 更新代码导读和启动/测试/打包引用，清理已完成批次的临时兼容代码与备份归属 | 全量回归、前端构建、实际新入口、冻结业务验证、桌面与内部安装包验证；报告区分自动验证与人工/外部门禁 |

R3/R5 内部的小组是为控制单次变动范围，不允许在失败时继续搬移下一组。确需合并批次或更换顺序，应先在计划中说明原因；计划确认不等于自动批准所有代码修改。

## 7. 验证口径与执行命令

实施开始时重新记录基线，不以本次只读检查作为已验证的重构结果。所有测试数据库放在系统临时目录或 `app/.local/` 的专用位置，测试启动前设置隔离 `SPECTRUM_DATA_DIR`，禁止使用正式用户库。

常用命令（在完成隔离配置后执行）：

```powershell
cd 'C:\Users\Leo\Desktop\地质局\app'
python -m pytest -q
python -m compileall -q backend tools tests
npm.cmd run frontend:build
npm.cmd --prefix frontend test
python tools/build_sidecar.py
python tools/verify_sidecar.py
```

定向测试由当前批次涉及的已有测试选择，不每批重复桌面全流程。新测试只覆盖搬移产生的新风险，例如隔离容器、循环依赖、资源定位、路由重复注册、升级顺序。涉及前端/原生文件能力的批次需要实际浏览器/桌面验证，不能只用源码字符串断言代替。

接口比较至少包括 HTTP 路径/方法、鉴权依赖、响应状态与模型、operation ID；运行比较包括进程密钥、会话、事件和输出。保留旧的准确契约，不能为得到通过结果放宽断言。

交付时记录受影响文件与旧符号到新位置的映射、命令及退出码、主流程/失败路径证据、剩余风险。追加到 [S21 报告](../acceptance-reports/S21/验收报告.md)，相关 S01/业务步骤只追加必要引用，历史报告正文不重写。测试/打包日志放 `app/.local/`，必要的长期证据放报告的 artifacts；不在根目录新增文件。

## 8. 明确不做的事情

- 不改变业务功能、URL、数据格式、算法口径、权限模型或数据库内容，不新增设备协议。
- 不引入新的 Web 框架、前端路由/状态管理库或通用依赖注入框架。
- 不重建已去掉的 `backend/app/`，不为了降低行数制造空目录或一行转发文件。
- 不因为文件未跟踪就删除；实施前建立可恢复快照。未经单独要求不执行 git 提交；源码与打包变更按当前获准批次执行。
- 两份 requirements 为引用关系，先保留；依赖锁定和开发依赖分离属于单独议题。
- 不批量改写历史验收和发布清单中的旧路径；当前导读更新后用补充说明解释历史路径。

## 9. 完成定义

入口文件以装配为主，API 不反向依赖入口，业务规则不留在用户/角色路由；前端页面和请求能按业务定位，公共组件有清楚归属。数据库迁移保持原执行语义；源码启动和冻结程序都通过受影响的主流程及失败路径验证。没有按文件行数或目录数量“达标”的要求。

## 10. R0/R1 实施记录

- R0 `passed`：已保存 242 个源码/配置/文档/资源文件的可恢复快照、文件哈希、Git 状态和完整 OpenAPI；基线 142 项测试、前端构建通过。基线位于 `app/.local/refactor-r1/baseline/`，不进入版本控制或安装包。
- R1 `passed`：新增 `runtime.py`、`api/dependencies.py`、`api/middleware.py`、`api/system.py` 及显式注册入口。运行对象挂在 `app.state.runtime`；`create_app()` 为测试创建隔离应用；认证依赖不再反向导入 main。剩余业务路由暂留 main，以请求依赖获取同一运行容器。
- `main.py` 从 2388 行减为 2002 行。服务装配与事件状态到 runtime；系统、关于/诊断、设置与运行消息 API 到 system；中间件与校验错误处理到 middleware。业务路由及用户/角色 SQL 尚未执行 R2/R3 搬移。
- 145 项全量测试通过；203 条路由的名称、权限与声明以及完整 OpenAPI 与 R0 一致。业务模块、资源、db.py、schemas.py、前端源码哈希不变。冻结后端构建与健康/模拟采集/旧读取器资源/强制停止后无残留验证通过。
- `sidecar_entry.py` 已通过独立 runtime 传递进程密钥，不再写 main 的全局变量。打包验证产物位于 `app/src-tauri/binaries/`；本批没有替换根目录程序或重建安装包，整体验证交付属于 R7。
- 下一批为 R2：身份与方法 API 及对应模型迁出。完成记录追加至 S21 验收报告，既有外部门禁不变。

## 11. R2 实施记录

- 用户明确要求“继续r2”；本批 `passed`，R3 尚未开始。
- 12 个身份/用户/角色/审计接口移至 `api/auth.py`；30 个方法/谱线/方法打印接口移至 `api/methods.py`。注册入口统一为 `api.register_api()`，保持固定路径的原有先后关系。
- 账户读写与审计移入 `AuthService`，四组写事务完整搬移。服务抛出不依赖 FastAPI 的 `AuthError`，接口边界转换回原有状态码和错误内容。登出操作也由认证服务处理。
- 原 `schemas.py` 改为 `schemas/` 包，6 个身份模型和 14 个方法相关模型进入 `auth.py`、`methods.py`。为保持本批边界，其余原模型暂留 `schemas/__init__.py`，同时显式导出已迁模型以兼容已有调用；它是分批迁移的过渡状态，R3/R6 再按对应业务归位，尚未达到目标中“包入口仅聚合导出”的最终结构。三个方法业务模块改为从 `schemas.methods` 导入，业务函数保持原样。
- `main.py` 从 2002 行减为 1576 行。完整 OpenAPI、203 条路由的名称/权限/声明及全部 84 个模型定义与 R1 相同。账户事务体在归一化依赖对象和异常类型名称后与原函数一致。
- 全量回归 `150 passed in 47.51s`；新增 4 组审计失败后的整笔回滚测试及 1 组 API 错误/零写入矩阵。方法保存、非法输入、打印和权限回归均包含在全量测试中。后端编译、打包及冻结健康/业务/资源验证通过。
- 本批恢复快照、OpenAPI 和日志在 `app/.local/refactor-r2/`。根目录 EXE 与安装包未替换，整体桌面交付仍在 R7；既有外部发布门禁不变。
- 下一批为 R3：其余后端接口分组迁出。

## 12. R3 实施记录

- 用户明确要求“继续r3”。R3 `passed`，R4 尚未开始。
- 按三组实施：队列/迁移/谱图定向 30 项通过；设备/色散/采集定向 33 项通过；分析/报告/维护/事件及扩展定向 37 项通过；每组通过后才搬移下一组。
- 其余业务接口分别迁入 `api/legacy_migration.py`、`spectrum_migration.py`、`result_migration.py`、`sample_queues.py`、`spectrum_viewer.py`、`devices.py`、`dispersion.py`、`acquisition.py`、`hardware_acquisition.py`、`mercury_calibration.py`、`analysis.py`、`postprocessing.py`、`reports.py`、`maintenance.py`。WebSocket 位于 `api/events.py`；测试扩展注册位于 `api/extensions.py`，保留测试构建门禁。
- `main.py` 从 1576 行减到 44 行，只保留 `lifespan()`、`create_app()` 和标准 app 入口。所有路由在 `api/__init__.py` 显式注册；未引入自动扫描或新的业务开关。
- 剩余 64 个模型全部按业务归入 `schemas/`，包入口只作显式兼容导出；后端内部导入改为指向模型所属文件。原全部 84 个模型定义一致。R6 不再需要继续拆分 schemas，只处理数据库基线和历史升级脚本。
- 全量 `150 passed in 46.08s`；增强既有扩展测试，验证同一进程由测试构建切回普通应用时不残留扩展路由。完整 OpenAPI 不变，原路由/辅助函数正文（除应用注册装配）逐项 AST 比较一致；业务模块正文、数据库、运行资源和前端未改语义。
- 本批基线、迁移脚本、比较结果和日志归入 `app/.local/refactor-r3/`。打包验证只更新构建目录，根目录程序与安装包仍留待 R7。
- 下一批为 R4：前端 api.ts 与本机能力调用拆分。

## 13. R4 实施记录

- 用户明确要求“继续r4”。R4 `passed`，R5 尚未开始。
- 原 1562 行 `frontend/src/api.ts` 替换为 `api/` 与 `platform/`；旧文件保存在 `app/.local/refactor-r4/`，不存在同级文件/目录解析歧义。
- 18 个业务模块保存各自类型和请求，`api/index.ts` 为 62 行兼容导出/组合入口。`api/client.ts` 保留 HTTP、重试和 ApiError，`api/events.ts` 生成事件连接地址；`platform/runtime.ts` 保留一次性握手缓存，`platform/files.ts` 保留文件保存、选择目录及浏览器回退。
- 181 个请求实现、95 个类型（含内部 DesktopRuntime）以及 7 个函数/类经 TypeScript 语法打印归一化比较一致；原 94 个公开类型和页面调用方式保留。跨业务类型使用 type-only 导入，业务模块不反向依赖 index。
- 前端 TypeScript/Vite 构建通过，1635 modules；既有 >500 kB bundle 提示保持。数值单测 4 项、架构/Tauri 契约 13 项通过；后端、Rust、页面组件和样式哈希与基线一致。
- 新增 `tests/frontend_api_browser.mjs`，`npm.cmd --prefix frontend run test:api` 可执行。需要可用 Playwright（当前通过 `PLAYWRIGHT_MODULE_PATH` 指定本机 bundled 包）和 Edge；测试自动启动隔离后端与 Vite，退出清理自身进程和临时数据库，日志归入 app/.local。
- 真实无界面 Edge 验证：初始化、错误密码、登录、方法创建/列表、真实 PDF 响应、PDF/UTF-8 CSV 下载、结构化 422、纯文本 HTTP 错误、浏览器不重试、204 登出、401 与页面会话恢复、WebSocket URL 和浏览器目录选择提示全部通过。
- 受控 Tauri 桥接验证：握手只调用一次、进程密钥、桌面重试、保存字节/类型、目录选择与保存取消、异常传递通过。本批未实际操作原生系统文件对话框；原生 GUI 与最终桌面集成留到 R7，不能把桥接测试视为真实对话框验收。
- 基线与结果在 `app/.local/refactor-r4/`。根目录 EXE 和安装包未更新；下一批 R5 为前端页面拆分与归位。

## 14. R5 实施记录（2026-09-14）

- 用户授权“继续r5”。R5 `passed`，R6 尚未开始。
- 三组完成：先 AuthForm、Sidebar/Header 与共享显示辅助代码；再方法、迁移、谱图和队列页面；最后 WorkspaceApp、其余页面、已有独立页面及公共组件归位。每组均通过构建与浏览器检查后继续。
- `App.tsx` 从 1725 行减到 82 行，只保留认证状态。跨页面状态原样进入 `layout/WorkspaceApp.tsx`，页面在 `pages/`、公共组件在 `components/`、布局组件在 `layout/`。方法面板按用途分别命名，不引入路由/状态管理库。
- 原 App 的 41 个顶层定义在忽略导出修饰符后语法比较一致；另有 33 个独立组件/样式文件归位，非导入部分保持原样。LegacySpectrumViewerPage 等既有代码保留。
- CSS 内容没有修改。先记录原依赖图的 16 个实际加载样式，再由 `styles/index.ts` 显式按原顺序加载；全局文件位于 styles/global.css，页面专用 CSS 随页面归位。构建 CSS 与基线逐字节一致。
- 最终 TypeScript/Vite 构建通过，1661 modules；数值单测 4 项，架构/Tauri 契约 13 项通过。后端、Rust、前端 api/ 与 platform/ 哈希不变。
- `npm.cmd --prefix frontend run test:pages` 通过：真实初始化/登录、三个方法视图、方法保存与刷新、空数值无新增版本、14 个可进入页面切换、1280/1920 下明暗主题无窗口横向溢出、真实只读身份及服务端 403。另 5 个需已发布当前方法的入口保持禁用，未绕过门禁或声称其业务数据流程已完成现场验收。
- 测试复用 R4 的 PDF/CSV 下载、HTTP 错误、会话恢复与受控桥接检查；真实原生对话框和最终桌面集成仍留待 R7。测试脚本修正了菜单固定状态、刷新后文本域标签和测试场景数据的定位/衔接，未通过修改产品逻辑掩盖失败。
- 可恢复基线、原文件和结果在 `app/.local/refactor-r5/`，当前导读、README 与测试路径已更新；根目录 EXE 和 NSIS 未更新。
- 下一批 R6：数据库基线及历史迁移脚本整理。


## 15. R6 实施记录（2026-09-14）

- 用户授权“继续r6”。R6 `passed`，R7 尚未开始；schemas 已在 R3 完成，本批仅整理数据库结构与历史迁移。
- db.py 从 2020 行减至 104 行，保留连接、锁、事务和迁移调度。migrations/baseline.py 保存建表、索引和迁移前兼容字段；defaults.py 保存迁移后的默认数据及不可变触发器；sql.py 保存不隐式提交的 SQL 执行器和结构检查。
- migrations/__init__.py 显式登记 v11_devices.py 至 v20_maintenance.py；版本保持 20，基线版本保持 10，不重新编号或合并历史步骤。迁移包不反向导入 db.py；upgrade.py 的副本验证和切换逻辑未改。
- 原 13 个辅助/迁移函数、迁移注册表、展开函数调用后的完整 Database 类 AST 一致，包含 SQL 字符串和事务顺序。固定时间后，新旧代码创建的空库完整 SQL 导出一致（268 个 sqlite_master 对象及默认记录）。基线和默认 SQL 仍作为完整历史块保留，没有为缩短文件而改写。
- 重构前 12 项定向检查通过；重构后 25 项数据库/升级定向检查通过，最终全量 163 passed in 50.56s，compileall 通过。新增 v10–v20 合成检查点续升、重复初始化不重跑迁移、方法及版本与已有迁移时间保留、后期迁移失败完整回滚及重试、暂存转换失败后原库字节不变。旧 JSON 帧转换及 BLOB 哈希测试继续通过，补充外键检查；合成检查点不宣称是各历史安装包的实库。
- build_sidecar.py 和 verify_sidecar.py 均退出码 0，冻结健康、v20 初始化、模拟 5 CCD/帧推进/停止和旧读取器资源验证通过。仅更新 app/src-tauri/binaries/；根目录 EXE、NSIS 和真实桌面验收留待 R7。
- 基线保存 237 个文件及 Git 状态，位于 app/.local/refactor-r6/baseline/；比较结果、脚本和日志同属 refactor-r6。当前导读及测试路径已同步；前端、业务服务、API、schemas、upgrade.py 与 Rust 源码哈希保持。系统临时目录 geospectrum-r6-compare-u2mtg637 的一次性比较副本因清理被策略拒绝而保留，后续比较已正确关闭连接并完成。
- 下一批 R7：整体验证与交付。S21 的真实硬件、签名和干净 Windows 外部门禁仍保留。


## 16. R7 实施与交付记录（2026-09-14）

- 用户授权“继续r7”。本计划 R0–R7 已完成；本批是结构重构的整体验证与内部交付，不表示 S21 正式发布门禁关闭。
- 最终结构：main.py 44 行、db.py 104 行、App.tsx 82 行；后端 api/、schemas/、migrations/ 与前端 api/、platform/、pages/、layout/、components/、styles/ 归属明确。保留仍被调用的显式公共导出，不新增一行转发文件；不存在旧 backend/app 或同级 api.ts。一次性搬移脚本、原文件及各批次可恢复基线归入 app/.local/refactor-r1 至 refactor-r7，不纳入发布包，未清理来源不明的用户文件。
- R7 工具修正：measure_tauri_startup.py 的临时数据归入 .local/test-runs，观察时长与测试终止不再冒充 UI 就绪时间/自然退出；build_release_manifest.py 纳入桌面 EXE 哈希并支持独立输出目录，避免覆盖此前发布记录。代码导读中残留的 App 集中页面描述已更新，当前源码路径与导读链接核对通过。
- 验证：全量 Python 163 passed in 53.99s；前端数值单测 4 passed；浏览器 test:pages 通过；Rust 3 passed；compileall 通过；完整 OpenAPI 与 R0 基线相等（173 paths）。工具更新后 S21 定向 10 passed；版本仍为 0.1.0，schema 仍为 20。
- 桌面构建使用 TypeScript/Vite 与 Tauri release，保留已有 >500 kB bundle 提示。已验证 R6 冻结后端，因此无需无改动重编 Python EXE；本批再次通过冻结业务验证，并对安装包内解出的后端执行验证。
- 用 seed_s24_ui.py 创建独立数据库，s24_frontend_regression.mjs 连接真实 release WebView：55 个布局状态无页面异常，覆盖采集/非法输入/分析/曲线/报告/模拟硬件停止/汞灯应用回滚/色散暂停停止/备份校验。选取明暗主题截图人工查看；不将模拟设备结果视为真实设备证据。
- 真实系统对话框：方法页导出 PDF 成功（30290 字节，2 页，包含 S16 方法文本）；原生保存取消与目录取消返回 null，目录选择返回所选隔离目录，非法文件名在对话框前拒绝。无进程密钥 HTTP 为 403。第二实例退出码 0 且未新增后端；正常窗口关闭后桌面及两个后端进程均消失。
- 首次 NSIS 构建因文件占用失败；关闭测试实例后单独 tauri bundle --ci 成功。重复打包提示已无法再次找到 bundle-type 占位变量，当前离线安装模式不使用 updater；包内 EXE 与构建 EXE 哈希一致。7-Zip 解包成功，8 个文件仅含两个程序、NSIS 支持文件和离线 WebView2；不含源码测试、缓存、.local。没有执行修改本机安装状态的安装/卸载，干净 Windows 的完整安装升级卸载仍为外部验收。
- 根目录 GeoSpectrum.exe 与 geospectrum-backend.exe 已备份后更新，空目录实启显示首次管理员入口，health=ok/schema=20，正常关闭无残留。安装包在 app/.local/releases/2026-09-14-refactor-r7/，发布清单在 docs/releases/0.1.0/2026-09-14-refactor-r7/。
- 本批 passed。代码签名、干净 Windows 10/11 与真实转角/汞灯硬件门禁保持；没有擅自提交 Git 或开始其他业务改造。


## 17. analysis 模块补充重构（2026-09-14）

用户在 R7 后明确授权继续处理 analysis.py。本轮仅拆分分析模块，不延伸到 methods/acquisition，不改算法、SQL、事务、API 或数据库版本。

- analysis.py 一次性替换为 analysis/ 包，原包路径保留公开 AnalysisService、AnalysisError 和算法导出。
- algorithms.py：重复统计、拟合、求值、高斯及寻峰；repository.py：原共享查询、结果装配、审计/消息写入辅助函数。
- service.py：分析创建、运行、慢进干预和取消；quality.py：重复质控；curves.py：曲线调整、拟合发布与合并；printing.py：曲线预览和 PDF。
- 采用显式对象组合，所有服务使用同一 Database；搬移完整事务，只调整共享辅助函数的引用，不通过多重继承或动态方法注入拼接。
- 验收：逐符号 AST 对比、S16/S17 黄金样本、采集与后处理/报告消费者、失败回滚、完整 OpenAPI、全量后端回归、冻结业务与分析链验证。更新根目录后端前保留可恢复副本；前端/桌面壳及 R7 安装包本轮不重建，交付状态在报告中单独说明。
- 当前状态：passed。原文件 1188 行已整体迁入包；service.py 343、algorithms.py 262、curves.py 256、repository.py 160、quality.py 139、printing.py 134 行，错误/序列化/公开入口分别 17/15/7 行。
- 39 个业务方法在仅归一化 self.repository 接收者后 AST 一致，12 个函数、错误类和 5 个常量 AST 一致；17 个公开服务方法签名和完整 OpenAPI 保持。算法层不依赖 SQLite/PDF；各业务对象共享同一 Database 与 repository，无多重继承或动态注入。
- 重构前 21 项定向通过，重构后全量 166 passed in 65.63s；最后仅整理导入和职责注释后 24 项定向通过，compileall 通过。新增质控/拟合/打印审计失败后完整数据库导出不变，恢复依赖后重试成功，完整性/外键检查通过。
- 冻结后端验证实际执行登录、质控、拟合、发布、结果合并、HTML 预览、PDF 与字节级重复打印；不存在的谱线返回 404。现有冻结模拟采集/读取器资源检查通过。最终冻结分析 PDF 为 23204 字节；打包后 API 使用真实 HTTP，不以源码测试替代。
- 根目录配套后端已备份后更新；前端与桌面壳不变，R7 安装包仍为其当时快照，未重建。基线、迁移脚本与日志在 app/.local/refactor-analysis/；报告追加 S21，并在 S16/S17 引用。本轮不继续拆分其他业务模块。


## 18. methods 与 legacy_migration 补充重构（2026-09-14）

用户明确授权将两个高优先级模块都重构。先 methods，核心验证通过后再 legacy_migration；本轮不进入其他业务模块。

- methods.py 替换为 methods/ 包：条件值/名称、几何换算、条件校验、共享查询、方法版本操作、当前运行状态分别归位。MethodService 保持原调用签名，已有内部消费者仍通过显式兼容方法访问；完整事务不切分、不增加数据库版本。
- legacy_migration.py 替换为 legacy_migration/ 包：读取器探测/副本读取、INI/BLOB/字段解析、Access 归一化、暂存与提交分别归位。原件始终只读，源文件指纹/mtime、幂等与失败回滚保持；调整读取器资源路径及对应测试。
- 按函数/方法 AST 核对，仅允许组合接收者和包相对路径调整；方法主流程、谱线、打印、真实 DIRECT.MTD/CFG/OPT、源完整性、原子回滚与消费者回归通过后运行全量后端、浏览器与冻结验证。
- 交付仅更新根目录配套后端，前端与桌面壳无改动，既有 R7 安装包保留其快照。本轮不重做安装包、不修改历史输入或提交 Git。
- 当前状态：passed。methods 原 922 行 → service 300、repository 239、validation 179、runtime 148、values 110、geometry 63、errors 31、入口 5 行；legacy_migration 原 833 行 → service 301、normalization 261、reader 111、records 98、configuration 97、sources 34、errors 24、入口 9 行。
- methods 的 32 个原业务方法、legacy 的 17 个方法经归一化组合接收者/相对路径后 AST 一致；所有原服务方法签名、15 个顶层函数/错误和全部常量保持。MethodService 保留被其他模块使用的显式方法，版本事务未拆散；LegacyMigrationService 保留提交失败注入钩子，归一化校验顺序与整个提交事务保持原样。
- methods 首组 19 passed；legacy 缺 Jet 测试的替换位置随新 reader 类迁移，断言未放宽。两模块/资源/发现/谱图/结果迁移定向 31 passed in 15.32s；最终全量 169 passed in 54.41s，compileall 通过，完整 OpenAPI 与 R0 一致。新增方法创建/发布/打开审计失败后完整数据库导出相等且可重试；原迁移实体插入失败全部回滚继续通过。
- 浏览器 test:pages 通过，真实方法保存/非法输入/权限检查保持。真实 DIRECT.MTD/CFG/OPT 在源码测试与冻结 API 都验证 3 方法/20 谱线/5 色散、源大小/mtime/SHA-256 保持、重复导入幂等、SQLite 完整性/外键通过；缺 Jet 时常规 API 启动仍可用。
- build_sidecar.py、verify_sidecar.py 与冻结方法/迁移专项脚本退出码 0。冻结程序完成方法生命周期、非法名称拒绝、旧方法真实读取/暂存/提交/幂等；读写发生在专用 .local 数据目录。读取器开发路径从 reader.py 向上 3 层定位 app/tools；打包资源仍由 importlib.resources 定位。
- 根目录配套后端已备份后更新。桌面壳/前端和 R7 安装包未重建；本轮基线 175 个文件、脚本与日志在 app/.local/refactor-methods-legacy/。其余后端文件哈希保持，导读/README/PLAN 与 S03/S06/S21 报告已同步；不继续其他业务重构。


## 19. postprocessing 与 method_printing 补充重构（2026-09-14）

用户授权拆分这两个模块。先后处理，定向回归通过后再方法打印；不扩展采集等其他模块。

- postprocessing/：EDT 转换、结果重算、编码导出与原子文件写入、共享查询、错误和编解码分别归位；保留 PostProcessingService 的调用签名和完整事务。
- method_printing/：文档组织/分页、HTML/PDF/字体、系统打印机适配分开；设置、预览、打印任务事务保留在原服务入口。系统调度失败仍保留渲染输入/PDF，现有错误码和保存顺序不变。
- 不改业务规则、格式、权限、API 或数据库版本；按 AST 和全部原方法签名核对，补核新旧文档/分页/HTML/PDF 一致性。运行原回归、关键失败路径、全量后端、浏览器和冻结专项。
- 根目录只更新配套后端；前端与桌面壳未变，R7 安装包不重建。临时备份与日志归入 app/.local/refactor-postprinting/，正式记录追加 S05/S18/S21。
- 当前状态：passed。

完成记录：postprocessing 原 684 行拆为 9 文件，最大 263 行；method_printing 原 662 行拆为 5 文件，最大 262 行。原方法签名、工具函数、常量与 24/22 个业务方法 AST 核对通过（仅归一化职责接收者）。171 项后端测试、compileall、浏览器 test:pages、后端打包、verify_sidecar 和冻结专项通过。A4 纵向与 A3 横向文档/分页/HTML 相同，固定 PDF 元数据后字节相同；两类强度的 CSV/TXT/Excel 共 6 组结果相同，完整 OpenAPI 不变。新增转换审计回滚与文件替换失败测试，原打印调度失败测试保持。

其余 113 个后端基线文件哈希相同。根目录配套后端已备份并更新；桌面壳与 R7 安装包未重建。正式结果见 docs/releases/0.1.0/2026-09-14-postprinting-refactor/verification.json，临时基线和日志在 app/.local/refactor-postprinting/。

## 20. 后续内部解耦规划（2026-09-14）

文件拆分后的内部依赖治理单独见 [后端内部解耦计划](INTERNAL_DECOUPLING_PLAN.md)。该计划覆盖打印适配、依赖装配、方法版本快照、采集事务内写入及纯计算边界，状态为 planned。本轮只编写计划，不修改已通过的 R0–R7 及补充拆分状态，也不启动 D1。
