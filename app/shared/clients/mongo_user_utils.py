"""
用户管理 MongoDB 工具模块
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
    """MongoDB 用户管理工具类"""

    def __init__(self):
        try:
            self.mongo_url = os.getenv("MONGO_URL")
            self.db_name = os.getenv("MONGO_DB_NAME")

            self.client = MongoClient(self.mongo_url)
            self.db = self.client[self.db_name]
            self.users = self.db["users"]

            # 创建唯一索引，保证用户名不重复
            self.users.create_index("username", unique=True)
            # 创建邮箱索引
            self.users.create_index("email", sparse=True)

            logger.info(f"UserMongoTool connected to MongoDB: {self.db_name}")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB for user management: {e}")
            raise


_user_mongo_tool: UserMongoTool | None = None

try:
    _user_mongo_tool = UserMongoTool()
except Exception as e:
    logger.warning(f"Could not initialize UserMongoTool on module load: {e}")


def get_user_mongo_tool() -> UserMongoTool:
    """获取 UserMongoTool 单例"""
    global _user_mongo_tool
    if _user_mongo_tool is None:
        _user_mongo_tool = UserMongoTool()
    return _user_mongo_tool


def find_user_by_username(username: str) -> Optional[dict]:
    """根据用户名查找用户"""
    tool = get_user_mongo_tool()
    try:
        return tool.users.find_one({"username": username})
    except Exception as e:
        logger.error(f"Error finding user by username: {e}")
        return None


def find_user_by_id(user_id: str) -> Optional[dict]:
    """根据用户ID查找用户"""
    tool = get_user_mongo_tool()
    try:
        return tool.users.find_one({"_id": ObjectId(user_id)})
    except Exception as e:
        logger.error(f"Error finding user by ID: {e}")
        return None


def create_user(username: str, password_hash: str, email: Optional[str] = None) -> Optional[str]:
    """
    创建新用户
    :return: 用户ID字符串，失败返回 None
    """
    tool = get_user_mongo_tool()
    try:
        document = {
            "username": username,
            "password_hash": password_hash,
            "email": email,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        result = tool.users.insert_one(document)
        logger.info(f"User created: {username}")
        return str(result.inserted_id)
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return None


def update_user(user_id: str, update_data: dict) -> bool:
    """更新用户信息"""
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
