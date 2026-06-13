from app.process.import_.agent.state import ImportGraphState


def generate_chunk_embeddings(state: ImportGraphState) -> ImportGraphState:
    """
        BGE-M3 批量生成混合向量
    `chunks``chunks`（含 dense/sparse vector）
    向量化服务：
    1. 读取 chunks
    2. 生成 dense_vector / sparse_vector
    3. 将向量结果补充回 chunks
    """

    return state