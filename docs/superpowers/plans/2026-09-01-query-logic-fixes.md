# 查询链路修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让查询、恢复、SSE 和历史接口使用可信用户身份，并修复 LangGraph 1.1 的 interrupt/resume 协议与历史关联。

**架构：** HTTP 层统一依赖认证用户；运行中 session 的 owner 保存在现有单进程任务状态中，持久历史 owner 从 Mongo 消息读取。图执行把返回值中的 `__interrupt__` 作为等待状态，恢复只使用 `Command(resume=...)`。

**技术栈：** FastAPI、LangGraph 1.1、MongoDB、SSE、pytest

---

## 前置条件与文件职责

先完成认证计划中的 Cookie/Bearer `get_current_user`。本计划修改：

- `app/api/http/query_server.py`：认证、所有权、interrupt/resume、HTTP 失败语义、SSE 终态。
- `app/shared/utils/task_utils.py`：单进程运行期 session owner。
- `app/infra/persistence/history_repository.py`：查询持久 session owner，复用 `clear_session()`。
- `app/shared/clients/mongo_history_utils.py`：按 session 查询 owner。
- `app/rag/query/item_name_confirm_service.py`、`answer_service.py`：写入真实 user_id。
- `app/process/query/agent/main_graph.py`：修正 web-only 路由优先级。
- `test/test_query_api.py`、`test/test_task_utils.py`、`test/test_sse_utils.py`：回归测试。

### 任务 1：建立 session owner 和历史用户关联

**文件：**
- 修改：`test/test_task_utils.py`
- 修改：`app/shared/utils/task_utils.py`
- 修改：`app/shared/clients/mongo_history_utils.py`
- 修改：`app/infra/persistence/history_repository.py`
- 修改：`app/rag/query/item_name_confirm_service.py`
- 修改：`app/rag/query/answer_service.py`

- [ ] **步骤 1：编写失败测试**

增加：

```python
def test_task_owner_round_trip():
    clear_task("s1")
    set_task_owner("s1", "u1")
    assert get_task_owner("s1") == "u1"


def test_user_message_passes_user_id(monkeypatch):
    save = Mock()
    monkeypatch.setattr(item_name_confirm_service.history_repository, "save_message", save)
    item_name_confirm_service.save_history_message({
        "session_id": "s1", "user_id": "u1", "original_query": "q",
        "rewritten_query": "q", "confirmed_item_name_list": [], "item_names": []
    })
    assert save.call_args.kwargs["user_id"] == "u1"
```

对助手消息增加同样断言，确保 `answer_service` 传递 `state["user_id"]`。

- [ ] **步骤 2：运行红灯**

```powershell
$env:JWT_SECRET='test-only-secret-at-least-32-bytes-long'
.\.venv\Scripts\python.exe -m pytest test/test_task_utils.py test/test_query_api.py -v
```

预期：owner API 不存在，保存消息缺少 `user_id`，测试 FAIL。

- [ ] **步骤 3：实现最少 owner 与写入代码**

在 `task_utils.py` 的模块字典中增加 `_task_owner: dict[str, str] = {}`，并实现：

```python
def set_task_owner(session_id: str, user_id: str) -> None:
    _task_owner[session_id] = user_id


def get_task_owner(session_id: str) -> str | None:
    return _task_owner.get(session_id)


def clear_task_owner(session_id: str) -> None:
    _task_owner.pop(session_id, None)
```

`clear_task()` 只清理进度和结果，不清理 owner，避免流式查询返回后、后台任务启动前出现所有权竞态。`/query` 在创建后台任务之前调用 `set_task_owner(session_id, user_id)`；中断态保留 owner，完成或失败后在历史已经持久化的前提下调用 `clear_task_owner()`。

在两个真实 `history_repository.save_message(...)` 调用中增加：

```python
user_id=state.get("user_id", "")
```

在 Mongo 工具实现：

```python
def get_session_owner(session_id: str) -> str | None:
    row = mongo_tool.chat_message.find_one(
        {"session_id": session_id, "user_id": {"$ne": ""}}, {"user_id": 1}
    )
    return row.get("user_id") if row else None
```

仓储只做同名委托方法。

- [ ] **步骤 4：运行绿灯**

运行任务 1 步骤 2 的同一命令，预期相关测试 PASS。

- [ ] **步骤 5：提交**

```powershell
git add app/shared/utils/task_utils.py app/shared/clients/mongo_history_utils.py app/infra/persistence/history_repository.py app/rag/query/item_name_confirm_service.py app/rag/query/answer_service.py test/test_task_utils.py test/test_query_api.py
git commit -m "fix: 关联查询会话与真实用户"
```

### 任务 2：保护查询、恢复、SSE 和历史资源

**文件：**
- 修改：`test/test_query_api.py`
- 修改：`app/api/http/query_server.py`

- [ ] **步骤 1：编写失败 API 测试**

```python
def test_query_requires_authentication():
    app.dependency_overrides.pop(get_current_user, None)
    response = client.post("/query", json={"query": "q", "is_stream": False})
    assert response.status_code == 401


def test_query_uses_token_user(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: {"_id": "u-auth", "role": "user"}
    invoke = Mock(return_value={"answer": "ok"})
    monkeypatch.setattr(query_server, "invoke_query_graph", invoke)
    client.post("/query", json={"query": "q", "user_id": "u-forged"})
    assert invoke.call_args.kwargs["user_id"] == "u-auth"


def test_other_users_session_is_forbidden(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: {"_id": "u2", "role": "user"}
    monkeypatch.setattr(query_server, "get_task_owner", lambda session_id: "u1")
    response = client.post("/resume", json={"session_id": "s1", "selected_value": "x"})
    assert response.status_code == 403
```

为 DELETE/GET history、GET sessions/user history 和 SSE 添加同一所有权断言。

- [ ] **步骤 2：运行红灯**

```powershell
$env:JWT_SECRET='test-only-secret-at-least-32-bytes-long'
.\.venv\Scripts\python.exe -m pytest test/test_query_api.py -v
```

预期：未认证当前返回成功或执行；伪造 user_id 被使用；跨用户操作未被拒绝。

- [ ] **步骤 3：实现统一所有权检查**

所有数据路由增加 `user: dict = Depends(get_current_user)`。使用：

```python
def _user_id(user: dict) -> str:
    return str(user.get("_id") or user.get("user_id"))


def _require_session_owner(session_id: str, user: dict) -> None:
    owner = get_task_owner(session_id) or history_repository.get_session_owner(session_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if owner != _user_id(user):
        raise HTTPException(status_code=403, detail="无权访问该会话")
```

`/query` 始终把 `_user_id(user)` 传给图，忽略请求体中的 `user_id`，并在调度后台任务前同步设置 task owner。`/sessions/{user_id}` 和 `/history/user/{user_id}` 要求路径 user_id 等于认证用户；session 历史、删除、恢复和 SSE 调用 `_require_session_owner()`。

DELETE 路由改为现有方法：

```python
delete_count = history_repository.clear_session(session_id)
```

- [ ] **步骤 4：运行绿灯**

运行任务 2 步骤 2 的同一命令，预期认证和所有权测试 PASS。

- [ ] **步骤 5：提交**

```powershell
git add app/api/http/query_server.py test/test_query_api.py
git commit -m "fix: 保护查询会话与历史接口"
```

### 任务 3：修复 LangGraph interrupt/resume

**文件：**
- 修改：`test/test_query_api.py`
- 修改：`app/api/http/query_server.py`

- [ ] **步骤 1：编写失败的协议测试**

```python
from types import SimpleNamespace
from unittest.mock import Mock, call


def test_invoke_returns_interrupt_without_marking_completed(monkeypatch):
    interrupt_value = {"title": "选择", "options": ["a", "b"], "type": "item_name_selection"}
    monkeypatch.setattr(query_server.query_graph_app, "invoke", lambda *a, **k: {
        "__interrupt__": [SimpleNamespace(value=interrupt_value)]
    })
    update = Mock()
    monkeypatch.setattr(query_server, "update_task_status", update)
    result = query_server.invoke_query_graph("s1", "q", False, "u1")
    assert result["interrupt"] == interrupt_value
    assert call("s1", TASK_STATUS_INTERRUPTED, False) in update.call_args_list


def test_resume_uses_command(monkeypatch):
    invoke = Mock(return_value={"answer": "ok"})
    monkeypatch.setattr(query_server.query_graph_app, "invoke", invoke)
    query_server._resume_graph_task("s1", "a", False)
    command = invoke.call_args.args[0]
    assert isinstance(command, Command)
    assert command.resume == "a"
```

- [ ] **步骤 2：运行红灯**

```powershell
.\.venv\Scripts\python.exe -m pytest test/test_query_api.py -k "interrupt or resume" -v
```

预期：首次结果被标 completed，且恢复参数是裸字符串，测试 FAIL。

- [ ] **步骤 3：实现 LangGraph 1.1 协议**

删除 `GraphInterrupt` 正常控制流。首次 invoke 后：

```python
interrupts = result_state.get("__interrupt__", ())
if interrupts:
    interrupt_value = interrupts[0].value
    update_task_status(session_id, TASK_STATUS_INTERRUPTED, is_stream)
    result_state["interrupt"] = interrupt_value
    push_to_session(session_id, SSEEvent.INTERRUPT, {
        "interrupt": interrupt_value, "session_id": session_id
    }) if is_stream else None
    return result_state
```

仅无中断时标 `COMPLETED`。恢复调用改为：

```python
result_state = query_graph_app.invoke(Command(resume=selected_value), config=config)
```

同步 query/resume 在 `result_state["interrupt"]` 存在时返回响应的 `interrupt` 字段；异常不再吞掉，记录状态后 `raise`，由 HTTP 层返回 500。

- [ ] **步骤 4：运行绿灯和隔离复现**

```powershell
.\.venv\Scripts\python.exe -m pytest test/test_query_api.py -k "interrupt or resume" -v
```

预期：协议测试全部 PASS。

- [ ] **步骤 5：提交**

```powershell
git add app/api/http/query_server.py test/test_query_api.py
git commit -m "fix: 适配 LangGraph 中断恢复协议"
```

### 任务 4：闭合 SSE 并恢复 web-only 分支

**文件：**
- 修改：`test/test_sse_utils.py`
- 修改：`test/test_query_api.py`
- 修改：`app/api/http/query_server.py`
- 修改：`app/process/query/agent/main_graph.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_final_event_is_followed_by_close(monkeypatch):
    pushed = []
    monkeypatch.setattr(query_server, "push_to_session", lambda sid, event, data=None: pushed.append(event))
    monkeypatch.setattr(query_server.query_graph_app, "invoke", lambda *a, **k: {"answer": "ok"})
    query_server.invoke_query_graph("s1", "q", True, "u1")
    assert pushed[-2:] == [SSEEvent.FINAL, SSEEvent.CLOSE]


def test_web_only_state_routes_directly_to_web():
    assert node_item_name_confirm_after({
        "confirmed_item_name_list": ["outside"], "is_web_only": True, "answer": ""
    }) == "node_web_search"


def test_multiple_workers_are_rejected(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(RuntimeError, match="single worker"):
        validate_runtime_config()
```

- [ ] **步骤 2：运行红灯**

```powershell
.\.venv\Scripts\python.exe -m pytest test/test_sse_utils.py test/test_query_api.py -k "close or web_only" -v
```

预期：没有 CLOSE，web-only 被 confirmed 分支抢先，测试 FAIL。

- [ ] **步骤 3：实现最少修复**

每个 FINAL 或 ERROR 终态后推送：

```python
push_to_session(session_id, SSEEvent.CLOSE, {})
```

中断态不关闭，以便恢复继续使用。将主图路由条件顺序改为：先处理 `answer`，再处理 `is_web_only`，最后处理 confirmed/history；web-only 返回 `node_web_search`。

由于 checkpoint、task owner 和 SSE 都仍是进程内存，在 `query_server.py` 增加并于创建 app 前调用：

```python
def validate_runtime_config() -> None:
    if int(os.getenv("WEB_CONCURRENCY", "1")) != 1:
        raise RuntimeError("query service requires single worker until shared state is configured")
```

- [ ] **步骤 4：运行绿灯**

运行任务 4 步骤 2 的同一命令，预期全部 PASS。

- [ ] **步骤 5：提交**

```powershell
git add app/api/http/query_server.py app/process/query/agent/main_graph.py test/test_sse_utils.py test/test_query_api.py
git commit -m "fix: 闭合查询流并恢复网络检索分支"
```
