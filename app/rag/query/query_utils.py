"""
query模块的一些工具方法
"""
from app.infra.persistence.history_repository import history_repository
from app.shared.runtime.logger import logger
# 查找session历史记录
def get_history_messages(session_id:str, limit:int = 10) -> list[dict]:
    """
    获取历史聊天记录! 倒序 limit=10
      只获取有效的聊天记录! item_names有数据为判断依据
    :param session_id: 筛选条件
    :param limit: 筛选数量
    :return: 有效数据集合
    """
    history_message_list = history_repository.list_recent(session_id=session_id,limit=limit)
    logger.info(f"查询历史记录数量:{len(history_message_list)}")
    # 有效校验
    final_message_list = [item for item in history_message_list if item.get("item_names") and len(item.get('item_names')) > 0]
    logger.info(f"校验后历史记录数量:{len(final_message_list)}")
    return final_message_list

# 拼接历史上下文
def build_history_context_text(final_message_list) -> str:
    """
     构建当前会话对应的上下文!
     历史记录已经完成了校验!
     约定格式: 序号,类型: 提问 / 回答 ,内容: text/rewritten_query , 关联主体: 1,2,3 \n
    :param history_message_list:
    :return:
    """
    history_text = ""
    # item -> 聊天记录 _id role text rewritten_query ts item_names image_urls
    for index, item in enumerate(final_message_list,start=1):
        history_text += (f"序号:{index},类型:{'提问' if item['role']=='user' else '回答'},"
                         f"内容:{item['rewritten_query'] if item['role']=='user' else item['text']},"
                         f"关联主体:{','.join(item['item_names'])}\n"
                         )
    logger.info(f"最终拼接历史记录上下文:{history_text}")
    return history_text

# 保存历史记录
def save_history_message(session_id,role,text,rewritten_query,item_names=[] ):
    """
    保存聊天记录
    :param state:
    :return:
    """
    history_repository.save_message(
        session_id = session_id,
        role=role,
        text=text,
        rewritten_query=rewritten_query,
        item_names=item_names
    )