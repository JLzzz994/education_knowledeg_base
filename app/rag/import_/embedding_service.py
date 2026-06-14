from app.infra.llm.providers import llm_provider
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.config import EMBEDDING_BATCH_SIZE
from app.shared.runtime.logger import logger, step_log

@step_log("require_chunks")
def require_chunks(state:ImportGraphState)->list[dict]:
    '''
    校验chunks
    :param state:
    :return:
    '''
    chunks = state.get('chunks')
    if not chunks or len(chunks) == 0:
        logger.error("chunks is empty 业务无法继续")
        raise Exception("chunks is empty 业务无法继续")
    return chunks
@step_log("embed_chunks")
def embed_chunks(chunks: list[dict], *, step: int = EMBEDDING_BATCH_SIZE) -> list[dict]:
    '''
    批量向量化
    :param chunks:
    :param step: 步长
    :return:
    '''
    # 1 定义最后返回的列表final_chunks
    final_chunks = []

    # 2 按批次遍历chunks
    for index in range(0,len(chunks),step):
        batch_chunks = chunks[index:index+step]
        batch_content= []
        for chunk in batch_chunks:
            batch_content.append(f"主体名:{chunk.get('item_name')},内容:{chunk.get('content')}")
        result = llm_provider.embed_documents(batch_content)
        dense_vector_list = result.get('dense')
        sparse_vector_list = result.get('sparse')
        for chunk,dense_vector,sparse_vector in zip(batch_chunks,dense_vector_list,sparse_vector_list):
            chunk_new = chunk.copy()
            chunk_new['dense_vector'] = dense_vector
            chunk_new['sparse_vector'] = sparse_vector
            final_chunks.append(chunk_new)
    logger.info(f"向量化完成，chunks数量：{len(final_chunks)}")
    return final_chunks

@step_log("generate_chunk_embeddings")
def generate_chunk_embeddings(state: ImportGraphState) -> ImportGraphState:
    """
    向量化服务：
    1. 读取 chunks
    2. 生成 dense_vector / sparse_vector
    3. 将向量结果补充回 chunks
    """
    # 1 require_chunks(state: dict) -> list[dict]:
    chunks = require_chunks(state)
    # 2 按批次批量向量化
    final_chunks = embed_chunks(chunks)
    state['chunks'] = final_chunks
    return state