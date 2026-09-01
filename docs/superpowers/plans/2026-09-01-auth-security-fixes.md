# 认证安全修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在保留现有 Bearer 客户端兼容性的同时，修复 Token 外泄、公开默认密钥、弱密码哈希和管理台 XSS。

**架构：** JWT 由 Header 或同 hostname Cookie 提供，登录跳转本身不再携带凭据。密码使用 stdlib scrypt 版本化格式，并在旧用户成功登录时惰性升级；前端渲染不再生成内联 JavaScript。

**技术栈：** FastAPI、Pydantic、stdlib hashlib/hmac/secrets、原生 JavaScript、pytest

---

## 文件职责

- 修改 `app/shared/utils/auth_utils.py`：JWT 配置校验、scrypt 和旧哈希兼容。
- 修改 `app/api/routers/auth_router.py`：Header/Cookie 认证、登录 Cookie、旧哈希升级。
- 修改 `app/api/schemas/auth_schema.py`：用户名和密码边界验证。
- 修改 `app/resources/html/login.html`：安全跳转，不在 URL 传 Token。
- 修改 `app/resources/html/admin.html`：使用 textContent/data 属性和事件监听器。
- 修改 `test/test_auth_utils.py`、`test/test_auth_api.py`：认证回归测试。
- 创建 `test/test_auth_frontend_security.py`：静态安全回归检查。

### 任务 1：JWT 配置和 scrypt 密码格式

**文件：**
- 修改：`test/test_auth_utils.py`
- 修改：`app/shared/utils/auth_utils.py`

- [ ] **步骤 1：编写失败测试**

增加：

```python
def test_new_password_hash_uses_scrypt():
    password_hash = hash_password("correct horse battery staple")
    assert password_hash.startswith("scrypt$")
    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("wrong", password_hash)


def test_legacy_hash_is_still_accepted():
    salt = "0123456789abcdef"
    digest = hashlib.sha256(f"{salt}legacy-pass".encode()).hexdigest()
    legacy = f"{salt}:{digest}"
    assert verify_password("legacy-pass", legacy)
    assert needs_password_rehash(legacy)


def test_public_jwt_secret_is_rejected(monkeypatch):
    monkeypatch.setattr(auth_utils, "JWT_SECRET", "your-secret-key-change-in-production")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        auth_utils.validate_auth_config()
```

- [ ] **步骤 2：运行红灯**

```powershell
.\.venv\Scripts\python.exe -m pytest test/test_auth_utils.py -v
```

预期：因 `needs_password_rehash`、`validate_auth_config` 不存在和 hash 格式仍为旧格式而 FAIL。

- [ ] **步骤 3：实现最少兼容代码**

在 `auth_utils.py` 使用固定参数：

```python
JWT_SECRET = os.getenv("JWT_SECRET")
_INSECURE_SECRET = "your-secret-key-change-in-production"
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def validate_auth_config() -> None:
    if not JWT_SECRET or JWT_SECRET == _INSECURE_SECRET:
        raise RuntimeError("JWT_SECRET must be configured with a private value")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def needs_password_rehash(password_hash: str) -> bool:
    return not password_hash.startswith("scrypt$")
```

`verify_password()` 先解析 `scrypt$...`；否则保留现有 `salt:sha256` 校验。`create_access_token()` 和 `decode_access_token()` 在使用密钥前调用 `validate_auth_config()`。

- [ ] **步骤 4：运行绿灯**

运行任务 1 步骤 2 的同一命令，预期全部 PASS。

- [ ] **步骤 5：提交**

```powershell
git add app/shared/utils/auth_utils.py test/test_auth_utils.py
git commit -m "fix: 强化 JWT 配置与密码哈希"
```

### 任务 2：Cookie 认证与旧密码惰性升级

**文件：**
- 修改：`test/test_auth_api.py`
- 修改：`app/api/routers/auth_router.py`
- 修改：`app/api/http/auth_server.py`

- [ ] **步骤 1：编写失败测试**

增加依赖函数的直接测试和登录测试：

```python
def test_get_current_user_accepts_cookie(monkeypatch):
    monkeypatch.setattr(auth_router, "decode_access_token", lambda token: {"sub": "u1"})
    monkeypatch.setattr(auth_router, "find_user_by_id", lambda user_id: {"_id": user_id, "role": "user"})
    user = auth_router.get_current_user(authorization=None, access_token="cookie-token")
    assert user["_id"] == "u1"


def make_legacy_hash(password: str) -> str:
    salt = "0123456789abcdef"
    digest = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{digest}"


def test_login_sets_http_only_cookie_and_upgrades_legacy_hash(monkeypatch):
    legacy = make_legacy_hash("secret")
    monkeypatch.setattr(auth_router, "find_user_by_username", lambda name: {
        "_id": "507f1f77bcf86cd799439011", "username": name, "password_hash": legacy
    })
    update = Mock(return_value=True)
    monkeypatch.setattr(auth_router, "update_user", update)
    response = client.post("/auth/login", json={"username": "alice", "password": "secret"})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    assert update.call_args.args[1]["password_hash"].startswith("scrypt$")
```

- [ ] **步骤 2：运行红灯**

```powershell
$env:JWT_SECRET='test-only-secret-at-least-32-bytes-long'
.\.venv\Scripts\python.exe -m pytest test/test_auth_api.py -v
```

预期：Cookie 参数和登录升级断言 FAIL。

- [ ] **步骤 3：实现认证依赖与 Cookie**

签名改为：

```python
def get_current_user(
    authorization: Optional[str] = Header(None),
    access_token: Optional[str] = Cookie(None),
) -> dict:
    token = access_token
    if authorization:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="无效的认证格式")
        token = authorization[7:]
    if not token:
        raise HTTPException(status_code=401, detail="未提供认证凭据")
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    user = find_user_by_id(payload.get("sub"))
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user
```

登录路由接收 `Response`，成功后执行：

```python
response.set_cookie(
    key="access_token",
    value=token,
    max_age=get_token_expire_time(),
    httponly=True,
    samesite="lax",
    secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
)
if needs_password_rehash(user.get("password_hash", "")):
    update_user(user_id, {"password_hash": hash_password(req.password)})
```

`auth_server.py` 在创建 app 前调用 `validate_auth_config()`，让缺失配置启动失败。

- [ ] **步骤 4：运行绿灯并验证缺密钥失败**

```powershell
$env:JWT_SECRET='test-only-secret-at-least-32-bytes-long'
.\.venv\Scripts\python.exe -m pytest test/test_auth_api.py -v
Remove-Item Env:JWT_SECRET
.\.venv\Scripts\python.exe -c "import app.api.http.auth_server"
```

预期：pytest PASS；最后一条以包含 `JWT_SECRET` 的 RuntimeError 失败。

- [ ] **步骤 5：提交**

```powershell
git add app/api/routers/auth_router.py app/api/http/auth_server.py test/test_auth_api.py
git commit -m "fix: 使用安全 Cookie 共享登录态"
```

### 任务 3：关闭 redirect Token 泄露

**文件：**
- 创建：`test/test_auth_frontend_security.py`
- 修改：`app/resources/html/login.html`
- 修改：`app/resources/html/chat.html`
- 修改：`app/resources/html/import.html`
- 修改：`app/resources/html/app.html`

- [ ] **步骤 1：编写静态失败测试**

```python
from pathlib import Path

HTML_DIR = Path("app/resources/html")


def test_login_never_places_token_in_redirect_url():
    source = (HTML_DIR / "login.html").read_text(encoding="utf-8")
    assert "searchParams.set('_token'" not in source
    assert "searchParams.set(\"_token\"" not in source
    assert "target.hostname !== window.location.hostname" in source


def test_receivers_do_not_parse_token_from_query_string():
    for name in ("chat.html", "import.html", "app.html"):
        source = (HTML_DIR / name).read_text(encoding="utf-8")
        assert "params.get('_token')" not in source
```

- [ ] **步骤 2：运行红灯**

```powershell
.\.venv\Scripts\python.exe -m pytest test/test_auth_frontend_security.py -v
```

预期：现有 `_token` URL 代码导致 FAIL。

- [ ] **步骤 3：实现安全跳转**

在 `login.html` 用唯一跳转函数替换两套 Token 拼接逻辑：

```javascript
function safeRedirect(rawTarget) {
  const fallback = `http://${window.location.hostname}:8001/app`;
  const target = new URL(rawTarget || fallback, window.location.origin);
  if (!['http:', 'https:'].includes(target.protocol) ||
      target.hostname !== window.location.hostname ||
      target.username || target.password) {
    window.location.assign(fallback);
    return;
  }
  window.location.assign(target.toString());
}
```

成功登录和已有登录态路径只调用 `safeRedirect(redirectTo)`。三个接收页面删除 `_token/_uid/_role` URL 解析，API 请求增加 `credentials: 'same-origin'`；同 hostname 跨端口 Cookie 会自动发送到各自页面所在服务。

- [ ] **步骤 4：运行绿灯**

运行任务 3 步骤 2 的同一命令，预期全部 PASS。

- [ ] **步骤 5：提交**

```powershell
git add test/test_auth_frontend_security.py app/resources/html/login.html app/resources/html/chat.html app/resources/html/import.html app/resources/html/app.html
git commit -m "fix: 禁止通过跳转 URL 传递令牌"
```

### 任务 4：消除管理台内联事件 XSS

**文件：**
- 修改：`test/test_auth_frontend_security.py`
- 修改：`app/api/schemas/auth_schema.py`
- 修改：`app/resources/html/admin.html`

- [ ] **步骤 1：编写失败测试**

```python
def test_admin_does_not_embed_user_data_in_inline_handlers():
    source = (HTML_DIR / "admin.html").read_text(encoding="utf-8")
    assert 'onclick="addWhitelist(' not in source
    assert 'onclick="removeWhitelist(' not in source
    assert "data-user-id" in source


def test_username_rejects_control_characters():
    with pytest.raises(ValidationError):
        RegisterRequest(username="bad\nname", password="12345678")
```

- [ ] **步骤 2：运行红灯**

```powershell
.\.venv\Scripts\python.exe -m pytest test/test_auth_frontend_security.py -v
```

预期：内联 `onclick` 和无限制 username 导致 FAIL。

- [ ] **步骤 3：实现最少修复**

用户名 schema 使用明确边界：

```python
username: str = Field(min_length=1, max_length=64, pattern=r"^[^\x00-\x1f\x7f]+$")
password: str = Field(min_length=8, max_length=256)
```

`admin.html` 创建单元格时对用户名使用 `textContent`；按钮仅设置 `button.dataset.userId = user.id` 和 `button.dataset.action`，在表格容器上统一监听 `click`，从 `event.target.dataset` 取值调用现有操作函数。

- [ ] **步骤 4：运行绿灯**

运行任务 4 步骤 2 的同一命令，预期全部 PASS。

- [ ] **步骤 5：提交**

```powershell
git add app/api/schemas/auth_schema.py app/resources/html/admin.html test/test_auth_frontend_security.py
git commit -m "fix: 消除管理台用户数据脚本注入"
```
