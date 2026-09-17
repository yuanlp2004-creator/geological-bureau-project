# 身份与审计模块导读（`auth`）

## 1. 模块定位

`auth` 负责首次管理员、本地账户、Argon2id 密码、进程内会话、角色权限和不可编辑审计查询。它不提供联网身份、第三方登录或持久化刷新令牌。

清单为 `AUTH_MANIFEST`，主要权限包括 `users.read/write`、`roles.write`、`audit.read`。

## 2. 代码入口

- 核心服务：[`backend/auth.py`](../../app/backend/auth.py)
- 请求认证和权限依赖：[`backend/api/dependencies.py`](../../app/backend/api/dependencies.py)，从当前 `app.state.runtime` 获取认证服务，不再导入 main 的全局对象。
- API：[`api/auth.py`](../../app/backend/api/auth.py) 中的 `/api/v1/auth/*`、`/api/v1/users`、`/api/v1/roles`、`/api/v1/audit`
- 数据模型：[`schemas/auth.py`](../../app/backend/schemas/auth.py) 中的登录、用户和角色模型
- 用户/角色事务与审计：`AuthService.create_user/update_user/create_role/update_role`；HTTP 状态转换只在 API 层执行。
- 前端：`pages/auth/AuthForm.tsx、UsersPage.tsx、AuditPage.tsx`（相对于 frontend/src/）。
- 测试：[`tests/test_auth.py`](../../app/tests/test_auth.py)

## 3. 密码与会话

`PASSWORD_HASHER` 固定使用 Argon2id。`hash_password()` 拒绝少于 8 个字符的密码；`verify_password()` 对无效哈希和类型错误统一返回失败，避免把解析异常暴露给登录端。

`AuthService.sessions` 是进程内字典：

- 登录成功生成随机令牌。
- `Session` 保存用户 ID、用户名、角色、权限和过期时间。
- 服务重启后所有会话失效。
- Tauri 不需要把长期令牌写入磁盘。

进程密钥是桌面进程边界，不是用户会话；二者不要混淆。

## 4. 首次管理员

`is_bootstrapped()` 以是否存在用户判断初始化状态。`bootstrap()` 必须在尚无用户时执行，并在一个事务内：

1. 建立内置角色和权限。
2. 创建首个管理员。
3. 分配系统管理员角色。
4. 写入 bootstrap 审计。

项目没有默认管理员密码。

## 5. 内置角色同步

`BUILTIN_ROLES` 定义四个系统角色：

- `system_administrator`
- `method_administrator`
- `analyst`
- `read_only_auditor`

`synchronize_builtin_permissions()` 使持久化的内置角色与代码矩阵完全一致，并记录权限增删。测试构建扩展权限只自动加入系统管理员。

内置角色的权限变化是兼容与安全变更，不能只改前端入口。

## 6. 权限依赖

`require_session()` 解析 Bearer 令牌并检查过期时间。`require_permission(key)` 在此基础上检查权限；路由用依赖注入声明安全边界。

前端的 `canWrite` 等布尔值只决定控件是否显示或禁用，后端权限依赖才是强制边界。

## 7. 数据表

- `users`：用户名、密码哈希和启用状态。
- `roles`、`permissions`：角色及权限字典。
- `user_roles`、`role_permissions`：多对多关联。
- `audit_events`：操作者、动作、目标、详情和时间。

审计事件没有编辑和删除 API。业务模块应在写事务中同时记录业务变更和审计。

## 8. 推荐阅读顺序

`BUILTIN_ROLES` → `Session` → `synchronize_builtin_permissions()` → `bootstrap()` → `login()` → `get_session()` → `api/dependencies.py` 的 `require_session()/require_permission()` → `api/auth.py` 路由 → `AuthService` 用户/角色事务。

## 9. 修改检查

- 密码和令牌不能进入日志或审计详情。
- 禁用用户后旧会话是否立即失效，应以当前实现和测试为准核对。
- 新写权限是否加入正确模块清单和角色。
- 自定义角色不能覆盖内置角色的锁定含义。
- 运行 `test_auth.py`、`test_api.py`、`test_architecture.py`。
