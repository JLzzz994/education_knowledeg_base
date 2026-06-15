"""
文件哈希 MongoDB 工具模块（REQ-06）
提供 file_hashes 集合的 CRUD 操作，用于文件去重和更新检测
集合字段: file_name, file_hash(唯一索引), item_name, task_id, file_size, import_time
"""
import os
from datetime import datetime
from typing import Optional

from pymongo import MongoClient
from dotenv import load_dotenv

from app.shared.runtime.logger import logger

load_dotenv()


class FileHashMongoTool:
    """
    MongoDB 文件哈希管理工具类
    连接 MongoDB 并操作 file_hashes 集合，提供文件去重能力
    """

    def __init__(self):
        try:
            self.mongo_url = os.getenv("MONGO_URL")
            self.db_name = os.getenv("MONGO_DB_NAME")

            self.client = MongoClient(self.mongo_url)
            self.db = self.client[self.db_name]
            self.file_hashes = self.db["file_hashes"]

            # 创建唯一索引：相同内容的文件不会重复导入
            self.file_hashes.create_index("file_hash", unique=True)
            # 创建普通索引：支持按文件名查询
            self.file_hashes.create_index("file_name")

            logger.info(f"FileHashMongoTool connected to MongoDB: {self.db_name}")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB for file hash management: {e}")
            raise


# ==================== 单例管理 ====================
_file_hash_mongo_tool: FileHashMongoTool | None = None

try:
    _file_hash_mongo_tool = FileHashMongoTool()
except Exception as e:
    logger.warning(f"Could not initialize FileHashMongoTool on module load: {e}")


def get_file_hash_mongo_tool() -> FileHashMongoTool:
    """获取 FileHashMongoTool 单例（延迟初始化）"""
    global _file_hash_mongo_tool
    if _file_hash_mongo_tool is None:
        _file_hash_mongo_tool = FileHashMongoTool()
    return _file_hash_mongo_tool


# ==================== 文件哈希操作 ====================

def find_by_file_hash(file_hash: str) -> Optional[dict]:
    """
    根据文件哈希查找记录
    :param file_hash: SHA-256 哈希值（64 字符十六进制）
    :return: 文件哈希文档，未找到返回 None
    """
    tool = get_file_hash_mongo_tool()
    try:
        return tool.file_hashes.find_one({"file_hash": file_hash})
    except Exception as e:
        logger.error(f"Error finding file by hash: {e}")
        return None


def find_by_file_name(file_name: str) -> list[dict]:
    """
    根据文件名查找记录（可能有多条同名但不同内容的文件）
    :param file_name: 原始文件名（含扩展名）
    :return: 文件哈希文档列表
    """
    tool = get_file_hash_mongo_tool()
    try:
        return list(tool.file_hashes.find({"file_name": file_name}))
    except Exception as e:
        logger.error(f"Error finding files by name: {e}")
        return []


def save_file_hash(
    file_name: str,
    file_hash: str,
    item_name: str,
    task_id: str,
    file_size: int,
) -> str:
    """
    保存文件哈希记录（导入完成后调用）
    1. 若哈希已存在则更新（upsert）
    2. 记录文件名、哈希、主体名、任务 ID、文件大小、导入时间
    :return: 文档 ID 字符串
    """
    tool = get_file_hash_mongo_tool()
    try:
        document = {
            "file_name": file_name,
            "file_hash": file_hash,
            "item_name": item_name,
            "task_id": task_id,
            "file_size": file_size,
            "import_time": datetime.now().isoformat(),
        }
        result = tool.file_hashes.update_one(
            {"file_hash": file_hash},
            {"$set": document},
            upsert=True,
        )
        logger.info(f"File hash saved: {file_name} ({file_hash[:16]}...)")
        return file_hash
    except Exception as e:
        logger.error(f"Error saving file hash: {e}")
        return ""


def delete_by_file_hash(file_hash: str) -> bool:
    """
    根据哈希删除文件记录（更新导入时先删旧记录）
    :return: 是否删除成功
    """
    tool = get_file_hash_mongo_tool()
    try:
        result = tool.file_hashes.delete_one({"file_hash": file_hash})
        return result.deleted_count > 0
    except Exception as e:
        logger.error(f"Error deleting file hash: {e}")
        return False
