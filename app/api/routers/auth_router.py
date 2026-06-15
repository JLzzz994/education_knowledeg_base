"""
认证服务路由模块
实现登录、注册、Token 刷新、用户信息、白名单管理、会话列表、历史记录查询等接口
遵循接口设计文档中的请求/响应格式
"""
from fastapi import APIRouter, Header, HTTPException, Depends
from typing import Optional

from app.shared.utils.auth_utils import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    get_token_expire_time,
)
from app.shared.clients.mongo_user_utils import (
    find_user_by_username,
    find_user_by_id,
    create_user,
    update_user,
)
from app.shared.clients.mongo_user_utils import get_user_mongo_tool
from app.api.schemas.auth_schema import (
    LoginRequest,
    RegisterRequest,
    WhitelistRequest,
    TokenData,
    UserInfo,
    UserListItem,
    ApiResponse,
    SessionListResponse,
    SessionItem,
    HistoryListResponse,
    HistoryItem,
)
from app.infra.persistence.history_repository import history_repository
from app.shared.runtime.logger import logger

router = APIRouter()


# ==================== 认证中间件 ====================

def get_current_user(authorization: str = Header(...)) -> dict:
    """
    认证依赖：从 Authorization 请求头解析 Bearer Token，返回当前用户信息
    :param authorization: 请求头中的 Authorization 值（格式：Bearer {token}）
    :return: 用户信息字典（包含 _id, username, role 等）
    :raises HTTPException: Token 无效或过期时返回 401
    """
    # 1. 解析 Bearer Token
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="无效的认证格式")
    token = authorization[7:]

    # 2. 解码并验证 Token
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")

    # 3. 从数据库获取用户信息
    user_id = payload.get("sub")
    user = find_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")

    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """
    管理员权限依赖：校验当前用户是否为 admin 角色
    :param user: 当前用户信息（由 get_current_user 提供）
    :return: 用户信息字典
    :raises HTTPException: 非管理员时返回 403
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可操作")
    return user


# ==================== 公开接口（无需认证） ====================

@router.post("/auth/login", response_model=ApiResponse)
def login(req: LoginRequest):
    """
    用户登录接口
    1. 根据用户名查找用户
    2. 校验密码
    3. 签发 JWT Token
    """
    # 1. 查找用户
    user = find_user_by_username(req.username)
    if user is None:
        return ApiResponse(code=401, message="用户名或密码错误")

    # 2. 校验密码
    if not verify_password(req.password, user.get("password_hash", "")):
        return ApiResponse(code=401, message="用户名或密码错误")

    # 3. 签发 Token
    user_id = str(user["_id"])
    token = create_access_token(user_id, req.username)

    logger.info(f"用户登录成功: {req.username}")
    return ApiResponse(
        code=200,
        message="登录成功",
        data={
            "access_token": token,
            "token_type": "bearer",
            "expires_in": get_token_expire_time(),
        }
    )


@router.post("/auth/register", response_model=ApiResponse)
def register(req: RegisterRequest):
    """
    用户注册接口
    1. 检查用户名是否已存在
    2. 哈希密码并创建用户（默认 role=user）
    """
    # 1. 检查用户名是否已存在
    existing = find_user_by_username(req.username)
    if existing is not None:
        return ApiResponse(code=409, message="用户名已存在")

    # 2. 哈希密码并创建用户
    password_hash = hash_password(req.password)
    user_id = create_user(req.username, password_hash, req.email)

    if user_id is None:
        return ApiResponse(code=500, message="注册失败，请稍后重试")

    logger.info(f"用户注册成功: {req.username}")
    return ApiResponse(
        code=200,
        message="注册成功",
        data={"user_id": user_id, "username": req.username}
    )


# ==================== 需认证接口 ====================

@router.post("/auth/refresh", response_model=ApiResponse)
def refresh_token(user: dict = Depends(get_current_user)):
    """
    刷新 Token 接口：验证当前 Token 有效后签发新 Token
    """
    user_id = str(user["_id"])
    username = user.get("username", "")
    new_token = create_access_token(user_id, username)

    return ApiResponse(
        code=200,
        message="刷新成功",
        data={
            "access_token": new_token,
            "token_type": "bearer",
            "expires_in": get_token_expire_time(),
        }
    )


@router.get("/auth/me", response_model=ApiResponse)
def get_me(user: dict = Depends(get_current_user)):
    """
    获取当前用户信息接口
    """
    return ApiResponse(
        code=200,
        message="success",
        data={
            "user_id": str(user["_id"]),
            "username": user.get("username"),
            "email": user.get("email"),
            "role": user.get("role", "user"),
            "created_at": user.get("created_at"),
        }
    )


@router.post("/auth/logout", response_model=ApiResponse)
def logout(user: dict = Depends(get_current_user)):
    """
    用户登出接口（无状态 JWT，前端清除 Token 即可）
    """
    logger.info(f"用户登出: {user.get('username')}")
    return ApiResponse(code=200, message="登出成功")


# ==================== 管理员接口 ====================

@router.post("/admin/whitelist", response_model=ApiResponse)
def add_whitelist(req: WhitelistRequest, admin: dict = Depends(require_admin)):
    """
    添加白名单用户：将目标用户的 role 从 user 升级为 whitelist
    """
    # 1. 查找目标用户
    target_user = find_user_by_id(req.user_id)
    if target_user is None:
        return ApiResponse(code=404, message="目标用户不存在")

    # 2. 检查当前角色
    current_role = target_user.get("role", "user")
    if current_role == "admin":
        return ApiResponse(code=403, message="不能修改管理员角色")
    if current_role == "whitelist":
        return ApiResponse(code=200, message=f"用户 {target_user.get('username')} 已在白名单中")

    # 3. 更新角色为 whitelist
    update_user(req.user_id, {"role": "whitelist"})
    logger.info(f"管理员 {admin.get('username')} 将用户 {target_user.get('username')} 添加至白名单")

    return ApiResponse(
        code=200,
        message=f"已将用户 {target_user.get('username')} 添加至白名单"
    )


@router.delete("/admin/whitelist/{user_id}", response_model=ApiResponse)
def remove_whitelist(user_id: str, admin: dict = Depends(require_admin)):
    """
    移除白名单用户：将目标用户的 role 从 whitelist 降级为 user
    """
    # 1. 查找目标用户
    target_user = find_user_by_id(user_id)
    if target_user is None:
        return ApiResponse(code=404, message="目标用户不存在")

    # 2. 检查当前角色
    current_role = target_user.get("role", "user")
    if current_role == "admin":
        return ApiResponse(code=403, message="不能修改管理员角色")
    if current_role == "user":
        return ApiResponse(code=200, message=f"用户 {target_user.get('username')} 已是普通用户")

    # 3. 更新角色为 user
    update_user(user_id, {"role": "user"})
    logger.info(f"管理员 {admin.get('username')} 将用户 {target_user.get('username')} 从白名单移除")

    return ApiResponse(
        code=200,
        message=f"已将用户 {target_user.get('username')} 从白名单移除"
    )


@router.get("/admin/users", response_model=ApiResponse)
def list_users(
    page: int = 1,
    page_size: int = 20,
    role: Optional[str] = None,
    admin: dict = Depends(require_admin),
):
    """
    用户列表接口（分页 + 角色过滤）
    """
    tool = get_user_mongo_tool()

    # 1. 构造查询条件
    query = {}
    if role:
        query["role"] = role

    # 2. 查询总数
    total = tool.users.count_documents(query)

    # 3. 分页查询
    skip = (page - 1) * page_size
    cursor = tool.users.find(query).skip(skip).limit(page_size)

    # 4. 组装返回数据
    items = []
    for user in cursor:
        items.append({
            "user_id": str(user["_id"]),
            "username": user.get("username"),
            "email": user.get("email"),
            "role": user.get("role", "user"),
            "created_at": user.get("created_at"),
        })

    return ApiResponse(
        code=200,
        message="success",
        data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }
    )


# ==================== 会话 & 历史记录接口 ====================

@router.get("/sessions/{user_id}", response_model=SessionListResponse)
def get_user_sessions(
    user_id: str,
    limit: int = 20,
    user: dict = Depends(get_current_user),
):
    """
    用户会话列表接口
    返回指定用户的去重会话列表，含最后活跃时间、消息数、最后查询等
    权限：仅能查看自己的会话列表，admin 可查看所有用户
    """
    # 权限校验：普通用户只能查看自己的会话
    current_user_id = str(user.get("_id", ""))
    if user.get("role") != "admin" and current_user_id != user_id:
        raise HTTPException(status_code=403, detail="只能查看自己的会话记录")

    sessions = history_repository.list_user_sessions(user_id, limit)

    return SessionListResponse(
        code=200,
        user_id=user_id,
        sessions=[SessionItem(**s) for s in sessions],
    )


@router.get("/history/user/{user_id}", response_model=HistoryListResponse)
def get_user_history(
    user_id: str,
    page: int = 1,
    page_size: int = 50,
    user: dict = Depends(get_current_user),
):
    """
    用户历史消息接口（分页）
    返回指定用户的全部历史消息，按时间倒序
    权限：仅能查看自己的历史，admin 可查看所有用户
    """
    # 权限校验
    current_user_id = str(user.get("_id", ""))
    if user.get("role") != "admin" and current_user_id != user_id:
        raise HTTPException(status_code=403, detail="只能查看自己的历史记录")

    messages, total = history_repository.list_user_history(user_id, page, page_size)

    items = []
    for msg in messages:
        items.append(HistoryItem(
            id=str(msg.get("_id", "")),
            session_id=msg.get("session_id", ""),
            role=msg.get("role", ""),
            text=msg.get("text", ""),
            item_names=msg.get("item_names") or [],
            ts=msg.get("ts", 0),
        ))

    return HistoryListResponse(
        code=200,
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )
