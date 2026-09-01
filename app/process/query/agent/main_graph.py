from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.process.query.agent.nodes.node_answer_output import node_answer_output
from app.process.query.agent.nodes.node_item_name_confirm import node_item_name_confirm
from app.process.query.agent.nodes.node_history_match import node_history_match
from app.process.query.agent.nodes.node_rerank import node_rerank
from app.process.query.agent.nodes.node_rrf import node_rrf
from app.process.query.agent.nodes.node_search_embedding import node_search_embedding
from app.process.query.agent.nodes.node_search_embedding_hyde import node_search_embedding_hyde
from app.process.query.agent.nodes.node_web_search_mcp import node_web_search_mcp
from app.process.query.agent.state import QueryGraphState
from app.shared.runtime.logger import logger

query_graph_builder = StateGraph(QueryGraphState)

query_graph_builder.add_node("node_item_name_confirm",node_item_name_confirm)
query_graph_builder.add_node("node_history_match",node_history_match)
query_graph_builder.add_node("node_search_embedding",node_search_embedding)
query_graph_builder.add_node("node_search_embedding_hyde",node_search_embedding_hyde)
query_graph_builder.add_node("node_web_search_mcp",node_web_search_mcp)
query_graph_builder.add_node("node_rrf",node_rrf)
query_graph_builder.add_node("node_rerank",node_rerank)
query_graph_builder.add_node("node_answer_output",node_answer_output)

# 定义初始节点
query_graph_builder.set_entry_point("node_item_name_confirm")
# query_graph_builder.add_edge("node_item_name_confirm","node_history_match")

# 条件边1：item_names识别之后
def node_item_name_confirm_after(state:QueryGraphState) :
    # 已确认item_names列表
    confirmed_item_name_list = state.get("confirmed_item_name_list",[])
    # 可选择item_names列表
    # options_item_name_list = state.get("options_item_name_list",[])
    # 模型识别主体
    item_names = state.get("item_names",[])

    if len(confirmed_item_name_list) > 0 :
        # 已确认item_names列表有值
        logger.info(f"本次有明确的item_name,跳转到history_match节点，item_names确认列表 {state.get('confirmed_item_name_list')}")
        return "node_history_match"

    elif not confirmed_item_name_list and len(item_names)>0 and state["is_web_only"]:
    # elif not confirmed_item_name_list and not options_item_name_list and len(item_names)>0 and state["is_web_only"]:
        # 该主体不在库中，进行网络搜索
        logger.info(f"向量数据库中未识别item_names，进行网络搜索!!!")
        return "node_web_search_mcp"
    else:
       # 大模型什么item_names都没识别出来
        logger.info(f"大模型未识别item_names，前端返回提问 ")
        return "node_answer_output"
# 添加条件边
query_graph_builder.add_conditional_edges(
    "node_item_name_confirm",
            node_item_name_confirm_after,
    {
        "node_history_match":"node_history_match",
        "node_web_search_mcp":"node_web_search_mcp",
        "node_answer_output":"node_answer_output"
    }
)
# 条件边2： 历史记录匹配之后
def node_history_match_after(state:QueryGraphState) :
    is_history = state.get("is_history",False)
    if is_history :
        # is_history为True说明在 历史记录中找到答案，且没滞后，直接到达输出节点
        logger.info(f"在历史记录找到答案，且没滞后，历史答案{state["answer"]}")
        return "node_answer_output"
    else:
        # 这里要么历史没搜到，要么历史记录滞后了，正常流程
        return "node_search_embedding", "node_search_embedding_hyde", "node_web_search_mcp"
 # 添加条件边
query_graph_builder.add_conditional_edges("node_history_match",node_history_match_after,{
    "node_answer_output":"node_answer_output",
    "node_search_embedding":"node_search_embedding",
    "node_search_embedding_hyde":"node_search_embedding_hyde",
    "node_web_search_mcp":"node_web_search_mcp",
})


query_graph_builder.add_edge("node_search_embedding","node_rrf")
query_graph_builder.add_edge("node_search_embedding_hyde","node_rrf")
query_graph_builder.add_edge("node_web_search_mcp","node_rrf")

query_graph_builder.add_edge("node_rrf","node_rerank")
query_graph_builder.add_edge("node_rerank","node_answer_output")
query_graph_builder.add_edge("node_answer_output",END)

# 创建内存检查点（支持 interrupt/resume 基于 thread_id 恢复状态）
memory = MemorySaver()

# 编译为可执行的图应用
query_graph_app = query_graph_builder.compile(checkpointer=memory)
