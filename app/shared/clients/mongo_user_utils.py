"""
用户管理 MongoDB 工具模块
提供 users 集合的 CRUD 操作，支持用户注册、查找、角色更新等功能
集合字段: username(唯一索引), password_hash, email(稀疏索引), role, created_at, updated_at
"""
import os
from datetime import datetime
from typing import Optional

from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

from app.shared.runtime.logger import logger

load_dotenv()


class UserMongoTool:
    """
    MongoDB 用户管理工具类
    连接 MongoDB 并操作 users 集合，提供用户 CRUD 能力
    """

    def __init__(self):
        try:
            # 从环境变量读取 MongoDB 连接配置
            self.mongo_url = os.getenv("MONGO_URL")
            self.db_name = os.getenv("MONGO_DB_NAME")

            # 建立连接并选择数据库和集合
            self.client = MongoClient(self.mongo_url)
            self.db = self.client[self.db_name]
            self.users = self.db["users"]

            # 创建唯一索引，保证用户名不重复
            self.users.create_index("username", unique=True)
            # 创建邮箱稀疏索引（允许为空，非空时加速查询）
            self.users.create_index("email", sparse=True)

            logger.info(f"UserMongoTool connected to MongoDB: {self.db_name}")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB for user management: {e}")
            raise


# ==================== 单例管理 ====================
_user_mongo_tool: UserMongoTool | None = None

# 模块加载时尝试初始化（失败不影响后续延迟初始化）
try:
    _user_mongo_tool = UserMongoTool()
except Exception as e:
    logger.warning(f"Could not initialize UserMongoTool on module load: {e}")


def get_user_mongo_tool() -> UserMongoTool:
    """获取 UserMongoTool 单例（延迟初始化，首次调用时建立连接）"""
    global _user_mongo_tool
    if _user_mongo_tool is None:
        _user_mongo_tool = UserMongoTool()
    return _user_mongo_tool


# ==================== 用户查询 ====================

def find_user_by_username(username: str) -> Optional[dict]:
    """
    根据用户名查找用户
    :param username: 用户名（唯一索引，查询高效）
    :return: 用户文档字典，未找到或异常返回 None
    """
    tool = get_user_mongo_tool()
    try:
        return tool.users.find_one({"username": username})
    except Exception as e:
        logger.error(f"Error finding user by username: {e}")
        return None


def find_user_by_id(user_id: str) -> Optional[dict]:
    """
    根据用户 ID 查找用户
    :param user_id: MongoDB ObjectId 字符串
    :return: 用户文档字典，未找到或异常返回 None
    """
    tool = get_user_mongo_tool()
    try:
        return tool.users.find_one({"_id": ObjectId(user_id)})
    except Exception as e:
        logger.error(f"Error finding user by ID: {e}")
        return None


# ==================== 用户创建 ====================

def create_user(username: str, password_hash: str, email: Optional[str] = None) -> Optional[str]:
    """
    创建新用户
    1. 构造用户文档（用户名、密码哈希、邮箱、时间戳）
    2. 插入 users 集合
    3. 返回插入后的 ObjectId 字符串
    :return: 用户 ID 字符串，失败返回 None
    """
    tool = get_user_mongo_tool()
    try:
        document = {
            "username": username,
            "password_hash": password_hash,
            "email": email,
            "role": "user",  # 默认角色为普通用户
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        result = tool.users.insert_one(document)
        logger.info(f"User created: {username}")
        return str(result.inserted_id)
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return None


# ==================== 用户更新 ====================

def update_user(user_id: str, update_data: dict) -> bool:
    """
    更新用户信息（通用更新方法）
    1. 自动追加 updated_at 时间戳
    2. 使用 $set 操作符更新指定字段
    :param user_id: MongoDB ObjectId 字符串
    :param update_data: 需要更新的字段字典，如 {"role": "whitelist"}
    :return: 是否有文档被修改
    """
    tool = get_user_mongo_tool()
    try:
        update_data["updated_at"] = datetime.now().isoformat()
        result = tool.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": update_data}
        )
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        return False
