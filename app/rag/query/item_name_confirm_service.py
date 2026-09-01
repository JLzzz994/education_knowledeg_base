from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import JsonOutputParser


from app.process.query.agent.state import QueryGraphState
from app.infra.persistence.history_repository import history_repository
from app.shared.runtime.logger import logger, step_log
from app.infra.llm.providers import llm_provider
from app.shared.runtime.load_prompt import load_prompt
from app.infra.vectorstore.milvus_gateway import milvus_gateway
from langgraph.types import interrupt

from app.rag.query.query_utils import get_history_messages,build_history_context_text


@step_log("get_data_and_validates")
def get_data_and_validates(state: QueryGraphState) -> tuple[str, str,str]:
    """
    进行必要参数校验!
       主要获取原始问题 original_query 和 session_id
    :param state:
    :return: 校验后结果
    """

    original_query = state.get("original_query")
    session_id = state.get("session_id")
    user_id = state.get("user_id")

    if not original_query or not session_id:
        logger.error(f"item_names识别节点：业务核心参数original_query或者session_id为空,业务无法继续进行!")
        raise ValueError(f"item_names识别节点：业务核心参数original_query或者session_id为空,业务无法继续进行!")

    return original_query, session_id, user_id


@step_log("call_llm_deal_data")
def call_llm_deal_data(history_text, original_query) -> dict:
    """
    调用模型进行问题重写和item_name识别
    注意: 返回的是json格式! 需要使用JsonOutputParser进行处理
    :param history_text: 历史记录
    :param original_query: 原始问题
    :return: dict
    """
    # 1. 加载模型 json model
    json_llm_client = llm_provider.chat(json_mode=True)
    # 2. 构建提示词
    prompt_text = load_prompt("rewritten_query_and_itemnames", history_text=history_text, query=original_query)
    messages = [
        HumanMessage(
            content=prompt_text
        )
    ]

    # 3. 构建调用链
    chain = json_llm_client | JsonOutputParser()
    # 4. 执行获取结果
    # {  item_names : [] , rewritten_query: 重写问题}
    result_dict = chain.invoke(messages)
    # 5. 结果校验
    if "item_names" not in result_dict:
        result_dict['item_names'] = []
    if "rewritten_query" not in result_dict:
        result_dict['rewritten_query'] = original_query
    # 6. 返回结果
    return result_dict


@step_log("query_item_name_milvus")
def query_item_name_milvus(item_names: list[str]) -> dict[str, list[dict]]:
    """
    从向量数据库进行item_name查询和结果处理! 注意是混合查询!!
    :param item_names: 模型识别,但是没有通过milvus确认的数据
    :return: 返回milvus中关联的高分数据! 但是先不截取
    """
    # 1. 定义前置存储容器
    milvus_result_dict = {}
    # 2. 循环处理每个item_name(模型返回)
    for item_name in item_names:
        # 3. 每个item_name向量化,获取对应的稠密和稀疏向量
        embedding_result = llm_provider.embed_documents([item_name])
        dense_vector = embedding_result['dense'][0]
        sparse_vector = embedding_result['sparse'][0]
        # 4. 组装对应annSearchRequest对象列表
        ann_request_list = milvus_gateway.create_requests(dense_vector, sparse_vector, limit=10)
        # 5. 进行混合数据检索,获取结果
        milvus_search_result = milvus_gateway.hybrid_search(
            collection_name=milvus_gateway.get_item_name_collection,
            reqs=ann_request_list,
            ranker_weights=(0.4, 0.6),
            norm_score=True,
            limit=5
        )
        # 6. 单条结果解析
        real_result = milvus_search_result[0]
        if not real_result or len(real_result) == 0:
            # 没有查到到数据
            logger.warning(f"模型提供的: {item_name} 没有检索到对应数据库数据! 跳过本次!!")
            continue

        # 变形
        current_item_name_list = [{"item_name": item_dict.get('entity', {}).get('item_name'),
                                   "score": item_dict.get('distance', 0)} for item_dict in real_result]
        milvus_result_dict[item_name] = current_item_name_list
        """
        item_name -> llm 

        {item_name: [{item_name:数据库中的name,score:distance}....5]}

        [
          [ -> real 
            {
               id: x,
               distance: 0.6,
               entity:{
                  item_name: 数据库中的name
               }
            },

            {
               id: x,
               distance: 0.6,
               entity:{
                  item_name: 数据库中的name
               }
            }
            5个..... 20 ->  权重排名器  -> 5 
          ]
        ]
        """
        # milvus_search_result [[{id:1,distance:0.8,entity:{item_name:向量查询}}]]
    # 7. 添加到对应的dict容器中
    # 8. 返回结果
    #  {item_name: [{item_name:数据库中的name,score:distance}....5]}
    return milvus_result_dict


@step_log("select_item_names")
def select_item_names(milvus_result_dict):
    """
      根据现有的数据,确定可选或者确认列表!
         {
           item_name :  [{item_name:数据库,score:0.72},{...}],  确认 1  可选 2
           item_name :  [{item_name:数据库,score:0.72},{...}],  确认 1  可选 2
           item_name :  [{item_name:数据库,score:0.72},{...}]   确认 1  可选 2
         }
    :param milvus_result_dict:
    :return:
    """
    # 1.定义两个列表
    confirmed_item_name_list = []
    options_item_name_list = []

    # 2. 循环处理每个item_name对应的列表
    for item_name, milvus_list in milvus_result_dict.items():
        # 没必要
        milvus_list.sort(key=lambda x: x['score'], reverse=True)
        # 筛选列表 高分[>0.7] 可选[0.6-0.7]
        high_item_names = [item['item_name'] for item in milvus_list if item['score'] > 0.7]
        md_item_names = [item['item_name'] for item in milvus_list if 0.6 < item['score'] <= 0.7]

        # 添加确认列表 1一个
        if len(high_item_names) > 0:
            confirmed_item_name_list.append(high_item_names[0])
            continue
        # 没有确认,可选的
        # 没有确认,可选的
        if len(md_item_names) > 0:
            # 注意 可能是多个,所以要继承
            options_item_name_list.extend(md_item_names[:2])
            continue

    return {
        "confirmed_item_name_list": confirmed_item_name_list,
        "options_item_name_list": options_item_name_list
    }


@step_log("change_state_status")
def change_state_status(state, item_name_dict, result_dict):
    """
     修改state状态
        确认列表有值
            item_names = 确认列表
            rewritten_query = rewritten_query
            return
        可选列表有值
            rewritten_query = rewritten_query
            answer = 客客气气...
            return
        都没有值
            rewritten_query = rewritten_query
            answer = 客客气气...
            return
    :param state:
    :param item_name_dict:
    :param rewritten_query:
    :return:
    """
    rewritten_query = result_dict.get("rewritten_query")
    # 获取大模型识别的items_name
    item_names = result_dict.get("item_names",[])
    # 获取已确认主体识别列表
    confirmed_item_name_list = item_name_dict.get('confirmed_item_name_list', [])
    # 获取可选择主体识别列表
    options_item_name_list = item_name_dict.get('options_item_name_list', [])

    # 回显数据
    state['item_names'] = item_names
    state['rewritten_query'] = rewritten_query

    if  len(confirmed_item_name_list) > 0:
        # 有确认的item_names!
        state["confirmed_item_name_list"] = confirmed_item_name_list
        return
    elif len(options_item_name_list) > 0:
        interrupt_data = interrupt({
            "title": "请选择您想询问的主体",
            "description": "识别到多个可能的主体，请选择其中一个",
            "options": options_item_name_list,
            "type": "item_name_selection"
        })
        
        selected_item = interrupt_data
        
        if selected_item and (selected_item in options_item_name_list):
            state["confirmed_item_name_list"] = [selected_item]
        else:
            logger.warning(f"用户选择了无效的主体: {selected_item}")
            state["confirmed_item_name_list"] = []
            state["answer"] = "用户选择了无效的主体,流程结束，请重新提问"
        return
    elif not confirmed_item_name_list and not options_item_name_list and item_names:
        # 可选列表和确认列表都没有值，但模型有识别出主体，说明库中暂时没有该主体相关的数据
        logger.info(f"该主体不存在向量数据库中，将进行网络搜索！")
        state["confirmed_item_name_list"] = item_names
        state["is_web_only"] = True
    else:
        # 全没值
        # 大模型啥都识别出来
        state["answer"] ="实在很抱歉，小T实在不知道您想问什么问题，请描述清楚重新提问吧"
        return




@step_log("save_history_message")
def save_history_message(state):
    """
    保存聊天记录
    :param state:
    :return:
    """
    confirmed_item_name_list = state.get("confirmed_item_name_list",[])

    history_repository.save_message(
        session_id=state['session_id'],
        role="user",
        text=state['original_query'],
        rewritten_query=state['rewritten_query'],
        item_names=confirmed_item_name_list if confirmed_item_name_list else state.get("item_names", [])
    )


@step_log("confirm_item_name")
def confirm_item_name(state: QueryGraphState) -> QueryGraphState:
    """
    意图确认服务：
    """

    # 1. 获取参数和校验(state) => original_query / session_id
    original_query, session_id,user_id = get_data_and_validates(state)

    # 2. 获取当前会话对应历史聊天记录(10条) [注意:只获取有效数据]
    history_message_list: list[dict] = get_history_messages(session_id, limit=10)

    # 3. 构建上下文,注意角色问题 user -> rewritten_query  assistant -> text
    history_text = build_history_context_text(history_message_list)

    # 4. 使用模型进行item_names和问题重写：得到模型识别的items_name和rewritten_query
    # 参数 history_text和original_query  响应: 字典 {item_names:[],rewritten_query:''}
    result_dict = call_llm_deal_data(history_text, original_query)

    item_name_dict = {}
    # 5. 进行校验,如果没有item_names无需调用向量查询
    if len(result_dict['item_names']) > 0:
        # 6.进行item_names内部识别到模型名称的向量化查询
        # 参数 item_names 即可! 响应: {item_name(这个是模型查询到的):[ 存储从milvus中匹配 {item_name: 名字 , score: 分数} .. 应该是5个]}
        milvus_result_dict: dict[str, list[dict]] = query_item_name_milvus(result_dict['item_names'])
        # 7. 获取确认和可选地列表  dict{确认:[0.7 + ] 可选:[ 0.6 - 0.7 ]}
        item_name_dict = select_item_names(milvus_result_dict)

    # 6.修改state状态
    change_state_status(state, item_name_dict, result_dict)

    # 7. 保存本次问题聊天记录
    save_history_message(state)

    return state