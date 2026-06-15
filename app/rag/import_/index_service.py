"""
Milvus 入库服务模块 - 将带向量的 chunks 写入 Milvus 向量数据库
职责：创建集合 schema 和索引 → 删除旧数据 → 批量插入新数据
支持幂等操作：重复导入同一文件时会先删除旧记录再插入新记录
"""
from pymilvus import DataType

from app.infra.vectorstore.milvus_gateway import milvus_gateway
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.config import MILVUS_CHUNK_CONTENT_MAX_LENGTH, MILVUS_DEFAULT_VARCHAR_MAX_LENGTH, MILVUS_VECTOR_DIM
from app.shared.runtime.logger import logger, step_log


@step_log('require_emb_chunks')
def require_emb_chunks(state: ImportGraphState) -> list[dict]:
    """
    校验 state 中的 chunks 是否已包含向量（embedding_service 必须先执行）
    :param state: 导入管线状态
    :return: 包含向量的 chunks 列表
    :raises ValueError: chunks 为空时抛出异常
    """
    chunks = state.get('chunks')
    if not chunks or len(chunks) == 0:
        logger.error("chunks is empty 业务无法继续")
        raise ValueError("chunks is empty 业务无法继续")
    return chunks


@step_log('prepare_chunks_collection')
def prepare_chunks_collection():
    """
    准备 Milvus 集合：若集合不存在则创建 schema + 索引
    集合 schema 包含字段：chunk_id(PK)、content、file_title、item_name、parent_title、title、part、dense_vector、sparse_vector
    索引：HNSW(COSINE) 用于稠密向量，SPARSE_INVERTED_INDEX(IP) 用于稀疏向量
    """
    # 1. 获取 Milvus 客户端和集合名称
    milvus_client = milvus_gateway.client
    chunks_collection = milvus_gateway.get_chunks_collection

    # 2. 集合已存在则跳过创建（幂等操作）
    if milvus_client.has_collection(collection_name=chunks_collection):
        return

    # 3. 定义集合 schema（auto_id 由 Milvus 自动生成主键，enable_dynamic_field 允许额外字段）
    schema = milvus_client.create_schema(auto_id=True, enable_dynamic_field=True)

    # 3.1 主键字段：chunk_id（自增 INT64）
    schema.add_field(
        field_name='chunk_id',
        datatype=DataType.INT64,
        is_primary=True
    )
    # 3.2 内容字段：存储 chunk 的完整文本内容
    schema.add_field(
        field_name='content',
        datatype=DataType.VARCHAR,
        max_length=MILVUS_CHUNK_CONTENT_MAX_LENGTH
    )
    # 3.3 元数据字段：文件标题、主体名称、父标题、标题、分片编号
    schema.add_field(
        field_name='file_title',
        datatype=DataType.VARCHAR,
        max_length=MILVUS_DEFAULT_VARCHAR_MAX_LENGTH
    )
    schema.add_field(
        field_name='item_name',
        datatype=DataType.VARCHAR,
        max_length=MILVUS_DEFAULT_VARCHAR_MAX_LENGTH
    )
    schema.add_field(
        field_name='parent_title',
        datatype=DataType.VARCHAR,
        max_length=MILVUS_DEFAULT_VARCHAR_MAX_LENGTH
    )
    schema.add_field(
        field_name='title',
        datatype=DataType.VARCHAR,
        max_length=MILVUS_DEFAULT_VARCHAR_MAX_LENGTH
    )
    schema.add_field(
        field_name='part',
        datatype=DataType.VARCHAR,
        max_length=MILVUS_DEFAULT_VARCHAR_MAX_LENGTH
    )
    # 3.4 向量字段：稠密向量（BGE-M3 输出 1024 维）和稀疏向量
    schema.add_field(
        field_name='dense_vector',
        datatype=DataType.FLOAT_VECTOR,
        dim=MILVUS_VECTOR_DIM
    )
    schema.add_field(
        field_name='sparse_vector',
        datatype=DataType.SPARSE_FLOAT_VECTOR,
    )

    # 4. 定义索引参数
    index_params = milvus_client.prepare_index_params()
    # 4.1 稠密向量索引：HNSW 算法，COSINE 相似度
    index_params.add_index(
        field_name='dense_vector',
        index_type='HNSW',
        metric_type='COSINE',
        params={
            "M": 64,
            "efConstruction": 100
        }
    )
    # 4.2 稀疏向量索引：倒排索引，内积相似度
    index_params.add_index(
        field_name='sparse_vector',
        index_type='SPARSE_INVERTED_INDEX',
        metric_type='IP',
        params={
            "inverted_index_algo": "DAAT_MAXSCORE"
        }
    )

    # 5. 创建集合（schema + 索引一起提交）
    milvus_client.create_collection(
        collection_name=chunks_collection,
        schema=schema,
        index_params=index_params
    )
    res = milvus_client.list_collections()
    logger.info(f"库中集合有{res}")


@step_log('remove_old_chunks')
def remove_old_chunks(file_title: str):
    """
    删除 Milvus 中指定文件的旧 chunks（支持重复导入同一文件时的数据覆盖）
    :param file_title: 文件标题，作为删除过滤条件
    """
    milvus_client = milvus_gateway.client
    chunks_collection = milvus_gateway.get_chunks_collection
    # 按 file_title 过滤删除，确保同一文件不会产生重复数据
    res = milvus_client.delete(
        collection_name=chunks_collection,
        filter=f'file_title=="{file_title}"'
    )
    logger.info(f'删除数据 结果是: {res}')


@step_log('insert_chunks')
def insert_chunks(chunks: list[dict]):
    """
    批量插入 chunks 到 Milvus（chunks 已包含 dense_vector 和 sparse_vector）
    :param chunks: 待插入的 chunk 列表
    """
    milvus_client = milvus_gateway.client
    chunks_collection = milvus_gateway.get_chunks_collection
    result = milvus_client.insert(
        collection_name=chunks_collection,
        data=chunks,
    )
    logger.info(f'插入数据成功 :{result}')


@step_log('index_chunks')
def index_chunks(state: ImportGraphState) -> ImportGraphState:
    """
    Milvus 入库服务主入口：校验 → 建表 → 删旧数据 → 插入新数据
    1. 校验 chunks 已包含向量
    2. 确保集合存在（不存在则创建）
    3. 删除该文件的旧数据（幂等）
    4. 批量插入新 chunks
    """
    # 1. 校验 chunks 已包含向量
    chunks = require_emb_chunks(state)
    # 2. 确保集合存在
    prepare_chunks_collection()
    # 3. 删除旧数据 + 插入新数据
    file_title = state.get('file_title', '')
    remove_old_chunks(file_title)
    insert_chunks(chunks)
    return state
