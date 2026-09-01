# 测试交付与集成修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让实际运行的三个 FastAPI 服务拥有可追踪、可安装、可执行的测试与一致的基础接口契约。

**架构：** 保留现有 `test/` 目录和 pytest 测试风格，只修复版本控制、开发依赖和测试指向。API 测试直接导入 `app.api.http.*_server.app`，依赖覆盖和 patch 均指向活动模块，不再依赖未挂载的重复 router。

**技术栈：** Python 3.11+、FastAPI TestClient、pytest、uv、Git

---

## 文件职责

- 修改 `.gitignore`：停止忽略项目测试目录。
- 修改 `pyproject.toml`：声明 pytest 开发依赖。
- 修改 `uv.lock`：锁定开发测试依赖。
- 创建 `test/conftest.py`：在测试收集前注入非生产 JWT 测试密钥。
- 修改 `app/api/http/auth_server.py`：提供认证服务健康检查。
- 修改 `app/api/http/import_server.py`：提供导入服务健康检查和未知任务 404。
- 修改 `test/test_auth_api.py`：验证活动认证 app。
- 修改 `test/test_import_api.py`：验证活动导入 app，不 patch 未挂载 router。
- 修改 `test/test_query_api.py`：配合认证和 interrupt/resume 新协议验证活动查询 app。

### 任务 1：恢复测试的版本控制和开发依赖

**文件：**
- 修改：`.gitignore:169`
- 修改：`pyproject.toml`
- 修改：`uv.lock`
- 创建：`test/conftest.py`

- [ ] **步骤 1：记录当前失败基线**

运行：

```powershell
.\.venv\Scripts\python.exe -c "import importlib.util; assert importlib.util.find_spec('pytest') is not None"
git ls-files test
```

预期：第一条以 `AssertionError` 失败；第二条无输出。

- [ ] **步骤 2：声明最小开发依赖并取消测试忽略**

从 `.gitignore` 删除精确行：

```text
test/
```

在 `pyproject.toml` 的 `[project]` 段之后增加：

```toml
[dependency-groups]
dev = [
    "pytest>=8.4,<9",
]
```

创建 `test/conftest.py`，确保认证模块在测试收集时可安全导入：

```python
import os

os.environ.setdefault("JWT_SECRET", "test-only-secret-at-least-32-bytes-long")
```

- [ ] **步骤 3：同步依赖和锁文件**

运行：

```powershell
uv sync --group dev
```

预期：退出码 0，`uv.lock` 更新，项目虚拟环境安装 pytest。

- [ ] **步骤 4：验证测试已可发现且可追踪**

运行：

```powershell
.\.venv\Scripts\python.exe -c "import pytest; print(pytest.__version__)"
git check-ignore test/test_auth_api.py
git status --short -- test
```

预期：打印 pytest 8.x；`git check-ignore` 退出码 1；`git status` 显示 `test/` 下文件为未跟踪或已跟踪改动。

- [ ] **步骤 5：提交测试基础设施**

```powershell
git add .gitignore pyproject.toml uv.lock test/conftest.py test
git commit -m "test: 恢复测试依赖与版本控制"
```

### 任务 2：统一基础健康与任务状态契约

**文件：**
- 修改：`test/test_auth_api.py`
- 修改：`test/test_import_api.py`
- 修改：`app/api/http/auth_server.py`
- 修改：`app/api/http/import_server.py`

- [ ] **步骤 1：先让活动 app 的契约测试准确失败**

在 `test/test_import_api.py` 中直接导入活动依赖：

```python
from app.api.http.import_server import app, require_import_permission

app.dependency_overrides[require_import_permission] = lambda: {
    "user_id": "test-user",
    "username": "tester",
    "role": "admin",
}
```

保留下列断言，并确保未知任务测试 patch 活动模块：

```python
def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "import"}


def test_unknown_task_returns_404():
    with patch("app.api.http.import_server.get_task_status", return_value=None):
        response = client.get("/status/missing")
    assert response.status_code == 404
```

在 `test/test_auth_api.py` 使用：

```python
def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "auth"}
```

- [ ] **步骤 2：运行红灯测试**

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest test/test_auth_api.py test/test_import_api.py -k "health_check or unknown_task" -v
```

预期：健康检查因 404 失败；未知任务因当前返回 200 失败。

- [ ] **步骤 3：添加最少生产实现**

在 `auth_server.py` 添加：

```python
@app.get("/health")
def health():
    return {"status": "ok", "service": "auth"}
```

在 `import_server.py` 添加：

```python
@app.get("/health")
def health():
    return {"status": "ok", "service": "import"}
```

并在 `task_status()` 获取状态后立即处理未知任务：

```python
if status is None:
    raise HTTPException(status_code=404, detail="任务不存在")
```

- [ ] **步骤 4：运行绿灯测试**

运行任务 2 步骤 2 的同一命令。

预期：3 个测试全部 PASS。

- [ ] **步骤 5：提交基础 API 契约**

```powershell
git add app/api/http/auth_server.py app/api/http/import_server.py test/test_auth_api.py test/test_import_api.py
git commit -m "fix: 统一服务健康与任务状态接口"
```

### 任务 3：清除测试对未挂载导入 router 的依赖

**文件：**
- 修改：`test/test_import_api.py`

- [ ] **步骤 1：扫描所有错误目标并形成红灯检查**

运行：

```powershell
rg -n "app\.api\.routers\.import_router|_calc_progress" test/test_import_api.py
```

预期：找到当前错误 import、patch 和不存在函数的测试。

- [ ] **步骤 2：把 patch 改到活动模块**

将状态函数 patch 统一改为：

```python
patch("app.api.http.import_server.get_task_status", ...)
patch("app.api.http.import_server.get_done_task_list", ...)
patch("app.api.http.import_server.get_running_task_list", ...)
patch("app.api.http.import_server.get_task_progress", ...)
patch("app.api.http.import_server.update_task_status", ...)
```

删除三个 `_calc_progress` 测试；进度算法已有独立的 `test/test_task_utils.py` 覆盖，不在 API 测试重复内部实现。

- [ ] **步骤 3：验证错误目标已经消失**

运行：

```powershell
rg -n "app\.api\.routers\.import_router|_calc_progress" test/test_import_api.py
.\.venv\Scripts\python.exe -m pytest test/test_import_api.py -v
```

预期：`rg` 无匹配；导入 API 测试全部 PASS。

- [ ] **步骤 4：提交活动路由测试修复**

```powershell
git add test/test_import_api.py
git commit -m "test: 覆盖实际导入服务路由"
```

### 任务 4：全链路回归与交付核验

**文件：**
- 修改：仅限前三份业务计划执行后仍失败的现有测试文件

- [ ] **步骤 1：运行完整语法与测试检查**

运行：

```powershell
.\.venv\Scripts\python.exe -m compileall -q app test
.\.venv\Scripts\python.exe -m pytest test -q
```

预期：两个命令均退出 0；pytest 无 failed/error。

- [ ] **步骤 2：核验所有运行必需文件已被 Git 跟踪**

运行：

```powershell
git ls-files app/api/http/auth_server.py app/api/routers/auth_router.py app/api/schemas/auth_schema.py app/resources/html/login.html app/resources/html/admin.html app/resources/html/app.html test
```

预期：列出六个认证运行文件以及全部测试文件。

- [ ] **步骤 3：核验没有被意外暂存的本地状态**

运行：

```powershell
git diff --check
git status --short
```

预期：`git diff --check` 退出 0；工作树仅保留用户原有且未纳入本次范围的改动。

- [ ] **步骤 4：如任务 4 修复过测试漂移则单独提交**

```powershell
git add test
git commit -m "test: 完成关键链路回归覆盖"
```

若步骤 1 已全绿且没有文件变化，不创建空 commit。
