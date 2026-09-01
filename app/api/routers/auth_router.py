"""
认证服务路由模块
实现登录、注册、Token 管理、用户管理、白名单等接口

接口清单:
  公开接口（无需 Token）:
    POST /auth/login       — 用户登录，返回 JWT Token
    POST /auth/register    — 用户注册

  需认证接口（需 Bearer Token）:
    GET  /auth/me          — 获取当前用户信息
    GET  /sessions/{uid}   — 用户会话列表
    GET  /history/user/{uid} — 用户历史消息

  管理员接口（需 admin 角色）:
    POST   /admin/whitelist      — 添加白名单用户
    DELETE /admin/whitelist/{uid} — 移除白名单用户
    GET    /admin/users           — 用户列表（分页+筛选）
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
    流程:
      1. 解析 "Bearer {token}" 格式
      2. 解码并验证 JWT Token（签名 + 过期时间）
      3. 从 MongoDB 获取用户文档
    :raises HTTPException 401: Token 无效、过期或用户不存在
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
    :raises HTTPException 403: 非管理员时返回 403
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


# ==================== 公开接口 ====================

@router.post("/auth/login", response_model=ApiResponse)
def login(req: LoginRequest):
    """
    用户登录接口
    流程:
      1. 根据用户名查找用户
      2. 校验密码（SHA-256 + 盐值比对）
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
    流程:
      1. 检查用户名是否已存在
      2. 哈希密码（SHA-256 + 随机盐）
      3. 创建用户文档（默认角色: user）
    """
    # 1. 检查用户名是否已存在
    existing = find_user_by_username(req.username)
    if existing is not None:
        return ApiResponse(code=409, message="用户名已存在")

    # 2. 哈希密码
    password_hash = hash_password(req.password)

    # 3. 创建用户
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

@router.get("/auth/me", response_model=ApiResponse)
def get_me(user: dict = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return ApiResponse(
        code=200,
        data=UserInfo(
            user_id=str(user["_id"]),
            username=user["username"],
            role=user.get("role", "user"),
            email=user.get("email"),
        ).model_dump()
    )


@router.get("/sessions/{user_id}", response_model=SessionListResponse)
def get_user_sessions(user_id: str, user: dict = Depends(get_current_user)):
    """
    获取用户会话列表
    权限: 只能查看自己的会话，管理员可查看所有人
    """
    # 权限检查：非本人且非管理员则拒绝
    if str(user["_id"]) != user_id and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权访问")

    sessions = history_repository.list_user_sessions(user_id)
    return SessionListResponse(
        sessions=[
            SessionItem(
                session_id=s.get("session_id", ""),
                title=s.get("title"),
                last_active=s.get("last_active"),
                message_count=s.get("message_count", 0),
            )
            for s in sessions
        ]
    )


@router.get("/history/user/{user_id}", response_model=HistoryListResponse)
def get_user_history(user_id: str, limit: int = 50, user: dict = Depends(get_current_user)):
    """
    获取用户历史消息（分页）
    权限: 只能查看自己的历史，管理员可查看所有人
    """
    if str(user["_id"]) != user_id and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权访问")

    records, total = history_repository.list_user_history(user_id, page_size=limit)
    return HistoryListResponse(
        items=[
            HistoryItem(
                id=str(r.get("_id")),
                session_id=r.get("session_id"),
                role=r.get("role"),
                text=r.get("text"),
                ts=r.get("ts"),
            )
            for r in records
        ],
        total=total
    )


# ==================== 管理员接口 ====================

@router.get("/admin/users", response_model=ApiResponse)
def list_users(page: int = 1, page_size: int = 20, role: Optional[str] = None,
               admin: dict = Depends(require_admin)):
    """
    用户列表接口（管理员专用）
    支持分页和角色筛选
    """
    from app.shared.clients.mongo_user_utils import get_user_mongo_tool
    tool = get_user_mongo_tool()

    query = {}
    if role:
        query["role"] = role

    total = tool.users.count_documents(query)
    skip = (page - 1) * page_size
    cursor = tool.users.find(query).skip(skip).limit(page_size).sort("created_at", -1)

    users = []
    for u in cursor:
        users.append({
            "id": str(u["_id"]),
            "username": u.get("username"),
            "role": u.get("role", "user"),
            "email": u.get("email"),
            "created_at": u.get("created_at"),
        })

    return ApiResponse(
        code=200,
        data={"items": users, "total": total, "page": page, "page_size": page_size}
    )


@router.post("/admin/whitelist", response_model=ApiResponse)
def add_to_whitelist(req: WhitelistRequest, admin: dict = Depends(require_admin)):
    """将用户添加到白名单（角色升级为 whitelist）"""
    user = find_user_by_id(req.user_id)
    if user is None:
        return ApiResponse(code=404, message="用户不存在")

    success = update_user(req.user_id, {"role": "whitelist"})
    if not success:
        return ApiResponse(code=500, message="操作失败")

    logger.info(f"管理员 {admin['username']} 将用户 {user['username']} 添加到白名单")
    return ApiResponse(code=200, message="已添加到白名单")


@router.delete("/admin/whitelist/{user_id}", response_model=ApiResponse)
def remove_from_whitelist(user_id: str, admin: dict = Depends(require_admin)):
    """将用户从白名单移除（角色降级为 user）"""
    user = find_user_by_id(user_id)
    if user is None:
        return ApiResponse(code=404, message="用户不存在")

    success = update_user(user_id, {"role": "user"})
    if not success:
        return ApiResponse(code=500, message="操作失败")

    logger.info(f"管理员 {admin['username']} 将用户 {user['username']} 从白名单移除")
    return ApiResponse(code=200, message="已从白名单移除")
