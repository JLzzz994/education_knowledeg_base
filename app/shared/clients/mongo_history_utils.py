"""
工具模块，负责提供 mongo history 相关的辅助能力。
REQ-07: 新增 user_id 关联、用户会话列表查询、用户历史查询、TTL 自动清理
"""
import os
from typing import Any
from datetime import datetime
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

from app.shared.runtime.logger import logger

# 加载.env文件中的环境变量，使os.getenv能读取到配置
load_dotenv()

# 历史记录保留天数（REQ-07: TTL 自动清理）
HISTORY_TTL_DAYS = int(os.getenv("HISTORY_TTL_DAYS", "30"))


class HistoryMongoTool:
    """
    MongoDB 历史对话记录读写工具类 (基于原生 PyMongo 实现)
    核心功能：封装MongoDB的连接、集合初始化、索引创建，为上层提供统一的数据库操作入口
    REQ-07 扩展：支持 user_id 关联、会话列表聚合查询、TTL 自动过期
    """
    def __init__(self):
        """
        类初始化方法：完成MongoDB的连接、数据库/集合获取、索引创建
        初始化失败会抛出异常并记录错误日志，确保程序感知连接问题
        """
        try:
            # 从环境变量读取MongoDB连接地址（敏感配置，不硬编码）
            self.mongo_url = os.getenv("MONGO_URL")
            # 从环境变量读取要使用的数据库名称
            self.db_name = os.getenv("MONGO_DB_NAME")


            # 创建MongoDB客户端实例，建立与数据库的连接
            self.client = MongoClient(self.mongo_url)
            # 获取指定名称的数据库对象 user 库
            self.db = self.client[self.db_name]

            # 获取对话记录的集合（相当于关系型数据库的表），集合名：chat_message  db.chat_message
            self.chat_message = self.db["chat_message"]
            # 获取永久存储历史记录的集合
            self.chat_history_message = self.db["chat_history_message"]
            # 存储文件传入及更新的表
            self.document_versions = self.db["document_versions"]

            # 为chat_message集合创建复合索引，提升查询性能
            # 索引规则：session_id升序 + ts降序，适配"按会话查最新记录"的核心查询场景
            # create_index自带幂等性：索引已存在时不会重复创建，无需额外判断
            self.chat_message.create_index([("session_id", 1), ("ts", -1)])

            self.chat_history_message.create_index([("user_id", 1), ("ts", -1)])
            self.document_versions.create_index([("_id", 1), ("ts", -1)])

            # REQ-07: 用户维度索引
            self.chat_message.create_index("user_id")
            self.chat_message.create_index([("user_id", 1), ("ts", -1)])
            # REQ-07: TTL 索引，自动清理过期记录
            self.chat_message.create_index("expire_at", expireAfterSeconds=0)

            # 记录成功日志，确认数据库连接和初始化完成
            logger.info(f"Successfully connected to MongoDB: {self.db_name}")

        except Exception as e:
            # 捕获所有初始化异常，记录详细错误日志
            logger.error(f"Failed to connect to MongoDB: {e}")
            # 重新抛出异常，让调用方感知初始化失败，避免使用未初始化的实例
            raise e


# 定义全局变量：存储HistoryMongoTool的单例实例
# 作用：避免多次创建HistoryMongoTool实例，从而避免重复建立MongoDB连接
_history_mongo_tool: HistoryMongoTool | None = None
# 模块加载时尝试初始化单例实例，实现预加载
# 目的：将数据库连接的初始化提前到模块加载阶段，避免第一次调用接口时才建立连接（提升首次响应速度）
try:
    _history_mongo_tool = HistoryMongoTool()
except Exception as e:
    # 初始化失败时仅记录警告日志，不抛出异常
    # 原因：模块加载阶段的异常可能导致整个程序启动失败，此处保留懒加载兜底（get_history_mongo_tool会再次尝试创建）
    logger.warning(f"Could not initialize HistoryMongoTool on module load: {e}")

def get_history_mongo_tool() -> HistoryMongoTool:
    """
    获取HistoryMongoTool的单例实例（懒加载模式）
    核心逻辑：全局实例为空时创建，不为空时直接返回，保证整个程序只有一个数据库连接实例
    :return: HistoryMongoTool的单例实例
    """
    # 声明使用全局变量，避免函数内视为局部变量
    global _history_mongo_tool
    # 懒加载：仅当全局实例为空时，才创建新的实例
    if _history_mongo_tool is None:
        _history_mongo_tool = HistoryMongoTool()
    # 返回单例实例
    return _history_mongo_tool



def clear_history(session_id: str) -> int:
    """
    清空指定会话的所有历史对话记录
    :param session_id: 会话唯一标识，用于筛选要删除的记录
    :return: 实际删除的文档数量，删除失败返回0
    """
    # 获取全局的HistoryMongoTool实例，使用单例模式避免重复创建数据库连接
    mongo_tool = get_history_mongo_tool()
    try:
        # 执行批量删除操作：删除所有session_id匹配的文档
        result = mongo_tool.chat_message.delete_many({"session_id": session_id})
        # 记录删除成功日志，包含删除数量和会话ID，便于问题排查
        logger.info(f"Deleted {result.deleted_count} messages for session {session_id}")
        # 返回实际删除的数量（delete_many的返回对象包含deleted_count属性）
        return result.deleted_count
    except Exception as e:
        # 捕获删除异常，记录错误日志，包含会话ID
        logger.error(f"Error clearing history for session {session_id}: {e}")
        # 异常时返回0，标识删除失败
        return 0

# 聊天记录会话级保存
def save_chat_message(
        session_id: str,
        role: str,
        text: str,
        rewritten_query: str = "",
        item_names: list[str] | None = None,
        image_urls: list[str] | None = None,
        message_id: str | None = None,
        user_id: str = "",
) -> str:
    """
    写入/更新单条会话记录到MongoDB
    支持两种模式：无message_id时新增记录，有message_id时更新已有记录
    :param session_id: 会话唯一标识，关联对话所属的会话
    :param role: 消息角色，固定值：user（用户）/assistant（助手）
    :param text: 对话核心内容，用户的提问或助手的回答
    :param rewritten_query: 重写后的查询语句（可选，用于检索增强等场景，默认空字符串）
    :param item_names: 关联的商品名称列表（可选，支持多商品，默认None）
    :param image_urls: 关联的图片URL列表（可选，默认None）
    :param message_id: 记录主键ID（可选，有值则更新，无值则新增）
    :param user_id: 用户ID（REQ-07，关联 users._id，用于用户维度历史查询）
    :return: 插入/更新的记录唯一标识（新增返回ObjectId字符串，更新返回传入的message_id）
    """
    # 生成当前时间的时间戳（秒级），用于记录消息的创建时间，后续用于排序和查询
    ts = datetime.now().timestamp()

    # 构造要插入/更新的文档数据（MongoDB的基本数据单元是文档，类似Python字典）
    document = {
        "user_id": user_id,  # REQ-07: 用户ID，支持用户维度历史查询
        "session_id": session_id,  # 会话ID，关联维度
        "role": role,  # 消息角色
        "text": text,  # 消息内容
        "rewritten_query": rewritten_query or "",  # 重写查询，空值处理为空字符串
        "item_names": item_names,  # 关联商品名称列表
        "image_urls": image_urls,  # 关联图片URL列表
        "ts": ts,  # 时间戳，排序和时间筛选维度
        "expire_at": datetime.fromtimestamp(ts + HISTORY_TTL_DAYS * 86400),  # REQ-07: TTL 过期时间
    }

    # 获取全局的HistoryMongoTool实例，使用单例模式
    mongo_tool = get_history_mongo_tool()
    # 判断是否传入主键ID，区分更新/新增逻辑
    if message_id:
        # 有message_id：执行更新操作（根据主键更新）
        result = mongo_tool.chat_message.update_one(
            {"_id": ObjectId(message_id)},  # 更新条件：主键匹配（需将字符串转为ObjectId类型）
            {"$set": document}  # 更新操作：$set表示只更新指定字段，保留其他字段
        )
        # 更新操作返回传入的message_id作为标识
        return message_id
    else:
        # 无message_id：执行新增操作
        result = mongo_tool.chat_message.insert_one(document)
        # 新增操作返回插入的ObjectId并转为字符串，便于上层使用（避免直接返回ObjectId对象）
        return str(result.inserted_id)

# 保存永久聊天记录
def save_chat_history_message(
        user_id: str,
        question: str,
        answer: str,
        item_names: list[str] | None = None,
        image_urls: list[str] | None = None,
        is_web_only:bool=False,
        message_id: str | None = None
) -> str:
    """
    写入/更新单条会话记录到MongoDB
    支持两种模式：无message_id时新增记录，有message_id时更新已有记录
    :param session_id: 会话唯一标识，关联对话所属的会话
    :param role: 消息角色，固定值：user（用户）/assistant（助手）
    :param text: 对话核心内容，用户的提问或助手的回答
    :param rewritten_query: 重写后的查询语句（可选，用于检索增强等场景，默认空字符串）
    :param item_names: 关联的商品名称列表（可选，支持多商品，默认None）
    :param image_urls: 关联的图片URL列表（可选，默认None）
    :param message_id: 记录主键ID（可选，有值则更新，无值则新增）
    :return: 插入/更新的记录唯一标识（新增返回ObjectId字符串，更新返回传入的message_id）
    """
    # 生成当前时间的时间戳（秒级），用于记录消息的创建时间，后续用于排序和查询
    ts = datetime.now().timestamp()

    # 构造要插入/更新的文档数据（MongoDB的基本数据单元是文档，类似Python字典）
    document = {
        "user_id": user_id,  # 用户ID，关联维度
        "question": question,  # 用户问题（重写后的问题，有可能是用户原问题）
        "answer":answer, # 系统回答
        "item_names": item_names,  # 关联商品名称列表
        "image_urls": image_urls,  # 关联图片URL列表
        "ts": ts,  # 时间戳，排序和时间筛选维度
        "is_web_only":is_web_only # 答案是否仅来源于网络
    }

    # 获取全局的HistoryMongoTool实例，使用单例模式
    mongo_tool = get_history_mongo_tool()
    # 判断是否传入主键ID，区分更新/新增逻辑
    if message_id:
        # 有message_id：执行更新操作（根据主键更新）
        result = mongo_tool.chat_history_message.update_one(
            {"_id": ObjectId(message_id)},  # 更新条件：主键匹配（需将字符串转为ObjectId类型）
            {"$set": document}  # 更新操作：$set表示只更新指定字段，保留其他字段
        )
        # 更新操作返回传入的message_id作为标识
        return message_id
    else:
        # 无message_id：执行新增操作
        result = mongo_tool.chat_history_message.insert_one(document)
        # 新增操作返回插入的ObjectId并转为字符串，便于上层使用（避免直接返回ObjectId对象）
        return str(result.inserted_id)



# 文件入库时间维护
def save_document_versions(
        _id: str,
        item_name: str,
        file_name: str,
        file_hash: list[str] | None = None,
        last_import_time: list[str] | None = None,
) -> str:
    """
    写入文件版本记录到 MongoDB
    :param _id: 文件唯一标识（主体名）
    :param item_name: 文件所属主体名称
    :param file_name: 文件名
    :param file_hash: 文件哈希值列表
    :param last_import_time: 最近导入时间列表
    :return: 插入记录的 ObjectId 字符串
    """
    # 生成当前时间的时间戳（秒级），用于记录消息的创建时间，后续用于排序和查询
    ts = datetime.now().timestamp()

    # 构造要插入/更新的文档数据（MongoDB的基本数据单元是文档，类似Python字典）
    document = {
        "_id": _id,  # 文件，关联维度
        "item_name": item_name,  # 文件主体
        "file_name":file_name, # 文件名
        "file_hash": file_hash,  # 文件哈希数据
        "last_import_time": last_import_time  # 时间戳，文件上传、更新时间
    }

    # 获取全局的HistoryMongoTool实例，使用单例模式
    mongo_tool = get_history_mongo_tool()


    # 无message_id：执行新增操作
    result = mongo_tool.document_versions.insert_one(document)
    # 新增操作返回插入的ObjectId并转为字符串，便于上层使用（避免直接返回ObjectId对象）
    return str(result.inserted_id)


def update_message_item_names(ids: list[str], item_names: list[str]) -> int:
    """
    批量更新历史会话记录的关联商品名称
    :param ids: 要更新的记录主键ID列表（字符串类型）
    :param item_names: 要设置的新商品名称列表
    :return: 实际更新的文档数量，更新失败返回0
    """
    # 获取全局的HistoryMongoTool实例，使用单例模式
    mongo_tool = get_history_mongo_tool()
    try:
        # 将字符串类型的主键列表转为MongoDB的ObjectId类型（数据库中主键是ObjectId类型）
        object_ids = [ObjectId(i) for i in ids]
        # 执行批量更新操作
        result = mongo_tool.chat_message.update_many(
            # 更新条件：复合条件，同时满足
            {
                "_id": {"$in": object_ids}# 主键在指定的ID列表中（批量筛选）
            },
            {"$set": {"item_names": item_names}}  # 更新操作：设置新的商品名称列表
        )
        # 记录更新成功日志，包含更新数量和新的商品名称
        logger.info(f"Updated {result.modified_count} records to item_names: {item_names}")
        # 返回实际更新的数量（modified_count：真正被修改的文档数，区别于matched_count）
        return result.modified_count
    except Exception as e:
        # 捕获批量更新异常，记录错误日志
        logger.error(f"Error updating history item_names: {e}")
        # 异常时返回0，标识更新失败
        return 0

# 获取会话级别历史记录session_id
def get_recent_messages(session_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """
    查询指定会话的最近N条对话记录，返回原始字典格式
    结果按时间正序排列，可直接喂给LLM作为上下文
    :param session_id: 会话唯一标识，用于筛选指定会话的记录
    :param limit: 条数限制，默认返回最近10条
    :return: 对话记录列表（字典格式），查询失败返回空列表
    """
    # 获取全局的HistoryMongoTool实例，使用单例模式
    mongo_tool = get_history_mongo_tool()
    try:
        # 构造查询条件：仅查询指定session_id的记录
        query = {"session_id": session_id}

        # 执行查询：按时间戳倒序取最近记录，限制返回条数
        # find(query)：获取符合条件的游标（惰性加载，不立即查询）
        # sort("ts", -1)：按ts字段倒序（从新到旧），用于快速获取最近消息
        # limit(limit)：限制返回的最大条数
        cursor = mongo_tool.chat_message.find(query).sort("ts", -1).limit(limit)
        # 将游标转为列表，触发实际数据库查询，获取所有符合条件的文档
        messages = list(cursor)
        # 返回查询结果列表
        return messages
    except Exception as e:
        # 捕获查询异常，记录错误日志
        logger.error(f"Error getting recent messages: {e}")
        # 异常时返回空列表，避免上层处理None报错
        return []

# 获取存储的历史记录：user_id匹配（用户历史记录匹配）
def get_recent_history_messages(user_id: str, limit: int = 30) -> list[dict[str, Any]]:
    """
    查询指定会话的最近N条对话记录，返回原始字典格式
    结果按时间正序排列，可直接喂给LLM作为上下文
    :param session_id: 会话唯一标识，用于筛选指定会话的记录
    :param limit: 条数限制，默认返回最近10条
    :return: 对话记录列表（字典格式），查询失败返回空列表
    """
    # 获取全局的HistoryMongoTool实例，使用单例模式
    mongo_tool = get_history_mongo_tool()
    try:
        # 构造查询条件：仅查询指定session_id的记录
        query = {"user_id": user_id}

        # 执行查询：按时间戳倒序取最近记录，限制返回条数
        # find(query)：获取符合条件的游标（惰性加载，不立即查询）
        # sort("ts", -1)：按ts字段倒序（从新到旧），用于快速获取最近消息
        # limit(limit)：限制返回的最大条数
        cursor = mongo_tool.chat_history_message.find(query).sort("ts", -1).limit(limit)
        # 将游标转为列表，触发实际数据库查询，获取所有符合条件的文档
        messages = list(cursor)
        # 返回查询结果列表
        return messages
    except Exception as e:
        # 捕获查询异常，记录错误日志
        logger.error(f"Error getting recent messages: {e}")
        # 异常时返回空列表，避免上层处理None报错
        return []

# 历史记录匹配（永久）
def history_match(query:dict):
    # query查询条件
    # 历史信息匹配

    # query = {
    #     "user_id": user_id,
    #     "question": question,
    #     "item_names": {"$in": [item_name]}
    # }

    # 获取全局的HistoryMongoTool实例，使用单例模式
    mongo_tool = get_history_mongo_tool()
    try:
        res = mongo_tool.chat_history_message.find_one(query)
        # res = {
        #         "user_id": user_id,  # 用户ID，关联维度
        #         "question": question,  # 用户问题（重写后的问题，有可能是用户原问题）
        #         "answer":answer, # 系统回答
        #         "item_names": item_names,  # 关联商品名称列表
        #         "image_urls": image_urls,  # 关联图片URL列表,
        #         "is_web_only"：False,# 是否仅来源于网络
        #         "ts": ts  # 时间戳，排序和时间筛选维度 }

        # 有返回字典格式和插入一致，没有返回None
        return res
    except Exception as e:
        # 捕获查询异常，记录错误日志
        logger.error(f"历史消息匹配异常: {e}")
        # 异常时返回空列表，避免上层处理None报错
        return []

# 文件时间戳文件的匹配函数
def document_versions_match(query: dict):
    # query查询条件
    # 历史信息匹配

    # query = {
    #      ”file_title“：file_title，
    #     "item_names":item_name
    # }

    # 获取全局的HistoryMongoTool实例，使用单例模式
    mongo_tool = get_history_mongo_tool()
    try:
        res = mongo_tool.document_versions.find_one(query)
        # 有返回字典格式和插入一致，没有返回None
        return res
    # {
    #         "_id": _id,  # 文件，关联维度
    #         "item_name": item_name,  # 文件主体
    #         "file_name":file_name, # 文件名
    #         "file_hash": file_hash,  # 文件哈希数据
    #         "last_import_time": last_import_time  # 时间戳，文件上传、更新时间
    #     }
    except Exception as e:
        # 捕获查询异常，记录错误日志
        logger.error(f"历史消息匹配异常: {e}")
        # 异常时返回空列表，避免上层处理None报错
        return []

# ==================== REQ-07: 用户维度查询 ====================

def get_user_sessions(user_id: str, limit: int = 20) -> list[dict]:
    """
    获取用户的会话列表（REQ-07）
    通过 MongoDB 聚合查询，按 session_id 分组，返回每个会话的最后活跃时间、消息数等
    :param user_id: 用户 ID
    :param limit: 返回的会话数量上限
    :return: 会话列表，每个元素含 session_id, last_active, message_count, last_query, item_names
    """
    mongo_tool = get_history_mongo_tool()
    try:
        pipeline = [
            # 1. 筛选指定用户的消息
            {"$match": {"user_id": user_id}},
            # 2. 按时间倒序排序（最新的消息排前面）
            {"$sort": {"ts": -1}},
            # 3. 按 session_id 分组，取每组的第一条消息（即最新消息）的字段
            {"$group": {
                "_id": "$session_id",
                "last_active": {"$first": "$ts"},
                "message_count": {"$sum": 1},
                "last_query": {"$first": "$text"},
                "item_names": {"$first": "$item_names"},
            }},
            # 4. 按最后活跃时间倒序（最近的会话排前面）
            {"$sort": {"last_active": -1}},
            # 5. 限制返回数量
            {"$limit": limit},
        ]
        results = list(mongo_tool.chat_message.aggregate(pipeline))
        # 格式化输出：将 _id 转为 session_id
        sessions = []
        for r in results:
            sessions.append({
                "session_id": r["_id"],
                "last_active": r.get("last_active", 0),
                "message_count": r.get("message_count", 0),
                "last_query": r.get("last_query", ""),
                "item_names": r.get("item_names") or [],
            })
        return sessions
    except Exception as e:
        logger.error(f"Error getting user sessions: {e}")
        return []


def get_user_history(user_id: str, page: int = 1, page_size: int = 50) -> tuple[list[dict], int]:
    """
    获取用户的历史消息列表（REQ-07，分页）
    :param user_id: 用户 ID
    :param page: 页码（从 1 开始）
    :param page_size: 每页条数
    :return: (消息列表, 总数)
    """
    mongo_tool = get_history_mongo_tool()
    try:
        query = {"user_id": user_id}
        # 查询总数
        total = mongo_tool.chat_message.count_documents(query)
        # 分页查询，按时间倒序
        skip = (page - 1) * page_size
        cursor = mongo_tool.chat_message.find(query).sort("ts", -1).skip(skip).limit(page_size)
        messages = list(cursor)
        return messages, total
    except Exception as e:
        logger.error(f"Error getting user history: {e}")
        return [], 0


# 主程序入口：仅当直接运行该脚本时执行，用于简单的功能测试
if __name__ == "__main__":
    # 简单测试代码：验证数据库的写入和查询功能是否正常
    # 测试会话ID，用于标识测试的对话记录
    sid = "000015_hybrid"
    # 1. 写入用户消息（手动指定ts=1000，便于测试排序）
    save_chat_message(sid, "user", "你好 (Hybrid)")
    # 2. 写入助手回复（手动指定ts=1001，按时间顺序紧跟用户消息）
    save_chat_message(sid, "assistant", "你好！我是基于原生 Mongo + LangChain 对象的助手。")
    # 3. 写入带关联商品的用户消息（手动指定ts=1002，测试item_names字段）
    save_chat_message(sid, "user", "这个万用表怎么换电池？", item_names=["混合万用表"])

    # 4. 查询指定会话的最近5条记录，验证查询功能
    print("--- 查询 LangChain 对象记录 ---")
    messages = get_recent_messages(sid, limit=5)
    # 打印查询到的记录数量
    print(f"查询到的记录数: {len(messages)}")
    # 遍历打印每条记录的详细内容
    for m in messages:
        print(f" {m}  ")
