from app.process.query.agent.state import QueryGraphState, copy_query_state
from app.shared.clients.mongo_history_utils import history_match,document_versions_match
from app.shared.runtime.logger import logger


def data_validates(state):
    """数据校验"""
    confirmed_item_name_list = state.get("confirmed_item_name_list")
    rewritten_query = state.get("rewritten_query")
    if not confirmed_item_name_list:
        logger.error("历史记录匹配节点关键参数confirmed_item_name_list为空！！！")
        raise ValueError("历史记录匹配节点关键参数confirmed_item_name_list为空！！！")
    if not rewritten_query:
        logger.error("历史记录匹配节点关键参数rewritten_query为空！！！")
        raise ValueError("历史记录匹配节点关键参数rewritten_query为空！！！")
    # 确认的列表item_names只取第一个就行
    return confirmed_item_name_list[0],rewritten_query


def history_match_data(confirmed_item_name, rewritten_query, state):
    """历史记录匹配并判断是否滞后"""""
    # 1.历史数据匹配
    query = {
        "user_id": state.get("user_id"),
        "question": rewritten_query,
        "item_names": {"$in": [confirmed_item_name]}
    }
    res = history_match(query)
    #  res = {
    #          "user_id": user_id,  # 用户ID，关联维度
    #         "question": question,  # 用户问题（重写后的问题，有可能是用户原问题）
    #         "answer":answer, # 系统回答
    #         "item_name": item_names,  # 关联商品名称列表
    #         "image_urls": image_urls,  # 关联图片URL列表
    #         "ts": ts  # 时间戳，排序和时间筛选维度
    #          "is_web_only":False # 是否仅web搜索
    #         }

    if res:
        # 匹配到历史记录

        if res["is_web_only"]:
            # 之前记录仅为网络搜索（有可能后面加了新文件呢）
            logger.info(f"匹配到历史记录，但为网络来源，本次正常走流程！！！")
            return

        # 历史时间戳
        ts = res["ts"]

        # 2.文件匹配
        d_query = {
            # "file_title":file_title,
            "item_name": confirmed_item_name
        }
        # 获取文件匹配结果
        s_res = document_versions_match(d_query)

        if s_res:
            # 匹配到文件
            # 获取文件时间戳
            fts = s_res["last_import_time"]

            # 3.历史记录时间大于文件更新时间：文件未更新
            if int(ts) > int(fts):
                logger.info(f"匹配到历史记录及文件，且没有过期与滞后，返回历史答案：{res["answer"]}")
                state["image_urls"] = res["image_urls"]
                state["answer"] = res["answer"]
                state["is_history"] = True
                return

            # state["history"] = True
            else:
                # 历史记录滞后，之前答案不能用
                logger.info(f"历史聊天记录回答过期，需要走正常匹配流程！！！")
                return
        else:
            # 有历史记录，但没有文件匹配，正常执行（有可能文件删除了）
            logger.info(f"匹配到历史记录，未匹配到文件，流程正常执行！！！")
            return
    else:
        # 未匹配到历史记录
        logger.info(f"未匹配到历史记录，流程继续，进入下一个节点！！！")
        return


def history_match_service(state):
    """
    历史匹配节点：检查用户问题是否与历史对话重复
    如果重复,查询数据时间和入库时间则直接返回历史答案，跳过后续检索流程
    """
    # 1. 校验数据
    confirmed_item_name,rewritten_query = data_validates(state)
    # 2.历史记录数据匹配，数据更新
    history_match_data(confirmed_item_name,rewritten_query,state)

    return state