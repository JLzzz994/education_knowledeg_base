# 关键安全与业务逻辑修复设计

## 目标

修复当前工作树审查确认的全部 P0、P1 和低成本 P2 问题，使认证、导入、查询三条主链路具备安全边界、正确失败语义和可运行的回归测试。

## 范围

本次包含：

- 认证：消除 URL Token 泄露、默认 JWT 密钥、弱密码哈希和管理台 XSS。
- 查询：补齐认证与资源所有权校验，修复 LangGraph interrupt/resume、历史删除、用户历史关联及错误状态码。
- 导入：阻止路径穿越，修复 Milvus `part` 类型、先删后插、活动 hash 与不支持类型假成功。
- 交付：纳入认证文件和测试，修正测试指向，声明测试依赖，增加健康检查。
- 低成本一致性：关闭 SSE 生命周期、修正仅网络检索分支、恢复文档版本更新。

本次不包含：

- Redis 或其他共享状态基础设施；服务仍明确限制为单 worker。
- Milvus/Mongo 跨系统分布式事务。
- 前端框架迁移或大规模目录重构。

## 总体策略

采用根因最小修复，不新增服务层或抽象框架。三个业务域分别修改，最后做跨域集成测试。

### 认证与 Token 传递

1. 登录接口设置 `HttpOnly`、`SameSite=Lax` 的访问令牌 Cookie，同时继续返回现有 JSON Token，兼容已有 API 客户端。
2. `get_current_user` 同时接受 Bearer Header 和 Cookie，Header 优先。
3. `redirect_to` 仅允许与登录页相同 hostname 的 HTTP(S) 地址或站内相对地址；禁止用户名、密码、非 HTTP(S) scheme 和外部 hostname。
4. 跳转不再携带 Token、用户 ID 或角色；同 hostname 的不同端口通过 Cookie 共享登录态。
5. 查询、导入、管理接口统一使用服务端认证结果，客户端提交的 `user_id` 不再决定身份。
6. JWT_SECRET 缺失或仍为公开占位值时启动失败；测试显式注入临时密钥。
7. 新密码使用 stdlib `hashlib.scrypt` 的版本化格式；旧 `salt:sha256` 仍可验证，成功登录后原位升级，避免强制重置密码。
8. 管理台删除内联事件处理器，用户名仅进入 DOM `textContent`，操作按钮通过 `data-user-id` 和事件监听器绑定。

### 查询链路

1. `/query`、`/resume`、`/stream`、历史和会话接口全部要求认证。
2. 查询请求中的用户身份由 Token 覆盖；历史、恢复、删除和 SSE 必须验证 session 属于当前用户。管理员不默认绕过所有权。
3. 首次图执行检查返回值中的 `__interrupt__`，向客户端/SSE 返回结构化的 `INTERRUPT` 状态，不标记完成。
4. 恢复使用 `Command(resume=selected_value)`；不存在、已完成或不属于当前用户的 session 返回 404/403/409。
5. 用户与助手消息均写入真实 `user_id`；删除路由调用仓储现有的 `clear_session()`。
6. 图执行异常转换为 5xx，非法输入转换为 4xx，不再用 HTTP 200 包装失败。
7. 终态发送 `FINAL` 后关闭并移除 SSE 队列；当前版本在文档和启动检查中限制单 worker。

### 导入链路

1. 上传文件名必须同时满足 POSIX 和 Windows basename 规则；拒绝绝对路径、盘符、UNC、`.`、`..` 和任何目录分隔符。
2. 保留当前 Milvus `part` VARCHAR schema，在写入前把 `part` 规范化为字符串，兼容已经创建的 collection，无需迁移。
3. 更新索引改为：查询旧 chunk 主键 → 插入新 chunks → 仅按旧主键删除旧 chunks。新插入失败时旧数据保持不变；旧数据删除失败时任务失败并保留可重试状态。
4. 所有 Milvus 字符串过滤器使用项目现有的 `escape_milvus_string()`。
5. `file_hashes` 表示文件名的当前活动版本：成功入库后按文件名 upsert 新 hash；去重只比较当前活动 hash。
6. 不支持的扩展名直接抛业务错误，任务状态为 FAILED。
7. 文档成功导入后更新历史匹配所需的文档版本记录。

### 测试与交付

1. 取消对 `test/` 的忽略并将认证运行文件纳入版本控制。
2. 在 `pyproject.toml` 增加开发测试依赖，不把 pytest 放入生产依赖。
3. 删除或改写针对未挂载 `import_router` 的测试；所有 API 测试直接覆盖实际 FastAPI app。
4. 三个服务提供 `/health`，未知任务返回 404。
5. 每个修复遵循红灯—绿灯：先运行最小失败测试，再修改生产代码，再运行同一测试和相关回归。

## 验收标准

- 外部 `redirect_to` 被拒绝或降级到安全默认页，任何跳转 URL 均不包含 Token。
- 未认证查询接口返回 401；跨用户 session 操作返回 403/404。
- 多主体查询返回 interrupt，合法选择可恢复并完成。
- 任意合法导入不会因整数 `part` 失败；模拟新数据插入失败时旧 chunks 仍存在。
- 路径穿越文件名返回 400，且任务目录外没有文件写入。
- v1 → v2 → v1 能真实切换活动版本，不出现假完成。
- 不支持文件任务为 FAILED。
- 旧 SHA-256 用户可登录，登录后密码哈希升级为 scrypt。
- pytest 测试被 Git 跟踪，核心回归测试全部通过；`compileall` 通过。

## 约束与风险

- Cookie 跨端口有效但不跨 hostname；本设计符合当前三个服务同 hostname、不同端口的部署方式。未来拆分域名时再增加显式 Cookie domain 或统一反向代理。
- Milvus 不提供本项目所需的跨操作事务；“先插新、后删旧”优先避免数据丢失，删除失败可能暂时产生重复数据，重试可收敛。
- 单 worker 是本次明确限制；需要多 worker 或高可用时，再引入 Redis checkpoint、任务状态和发布订阅。
