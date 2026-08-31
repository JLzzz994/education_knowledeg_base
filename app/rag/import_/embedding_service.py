"""
向量化服务模块 - 批量生成稠密向量和稀疏向量
职责：读取 state 中的 chunks，调用 BGE-M3 模型为每个 chunk 生成 dense_vector 和 sparse_vector
向量化输入格式："主体名:{item_name},内容:{content}"，将主体名称与内容拼接以增强语义
"""
from app.infra.llm.providers import llm_provider
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.config import EMBEDDING_BATCH_SIZE
from app.shared.runtime.logger import logger, step_log


@step_log("require_chunks")
def require_chunks(state: ImportGraphState) -> list[dict]:
    """
    校验 state 中的 chunks 是否存在且非空
    :param state: 导入管线状态
    :return: chunks 列表
    :raises ValueError: chunks 为空时抛出异常
    """
    chunks = state.get('chunks')
    if not chunks or len(chunks) == 0:
        logger.error("chunks is empty 业务无法继续")
        raise Exception("chunks is empty 业务无法继续")
    return chunks


@step_log("embed_chunks")
def embed_chunks(chunks: list[dict], *, step: int = EMBEDDING_BATCH_SIZE) -> list[dict]:
    """
    按批次调用 BGE-M3 模型，为每个 chunk 生成稠密向量和稀疏向量
    :param chunks: 待向量化的 chunk 列表，每个 chunk 需包含 item_name 和 content
    :param step: 批次大小，默认从 config 读取 EMBEDDING_BATCH_SIZE
    :return: 包含 dense_vector 和 sparse_vector 的新 chunk 列表（不修改原始 chunk）
    """
    # 1. 定义返回列表（深拷贝 chunk，不污染原始数据）
    final_chunks = []

    # 2. 按批次遍历 chunks，避免一次加载过多数据到显存
    for index in range(0, len(chunks), step):
        # 2.1 切片获取当前批次的 chunks
        batch_chunks = chunks[index:index + step]

        # 2.2 拼接向量化输入文本："主体名:xxx,内容:xxx"
        batch_content = []
        for chunk in batch_chunks:
            batch_content.append(f"主体名:{chunk.get('item_name')},内容:{chunk.get('content')}")

        # 2.3 调用 BGE-M3 模型批量向量化，返回 {"dense": [[...], ...], "sparse": [{...}, ...]}
        result = llm_provider.embed_documents(batch_content)
        dense_vector_list = result.get('dense')
        sparse_vector_list = result.get('sparse')

        # 2.4 将向量结果附加到 chunk 副本中
        for chunk, dense_vector, sparse_vector in zip(batch_chunks, dense_vector_list, sparse_vector_list):
            chunk_new = chunk.copy()
            chunk_new['dense_vector'] = dense_vector
            chunk_new['sparse_vector'] = sparse_vector
            final_chunks.append(chunk_new)

    logger.info(f"向量化完成，chunks数量：{len(final_chunks)}")
    return final_chunks


@step_log("generate_chunk_embeddings")
def generate_chunk_embeddings(state: ImportGraphState) -> ImportGraphState:
    """
    向量化服务主入口：读取 chunks → 批量向量化 → 回写 state
    1. 校验 chunks 存在
    2. 按批次调用 BGE-M3 生成 dense_vector / sparse_vector
    3. 将带向量的 chunks 写回 state
    """
    # 1. 校验并获取 chunks
    chunks = require_chunks(state)
    # 2. 批量向量化
    final_chunks = embed_chunks(chunks)
    # 3. 回写 state，下游节点（index_service）使用
    state['chunks'] = final_chunks
    return state
