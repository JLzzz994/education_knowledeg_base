from pymilvus import DataType

from app.infra.vectorstore.milvus_gateway import milvus_gateway
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.config import MILVUS_CHUNK_CONTENT_MAX_LENGTH, MILVUS_DEFAULT_VARCHAR_MAX_LENGTH, MILVUS_VECTOR_DIM
from app.shared.runtime.logger import logger, step_log

@step_log('require_emb_chunks')
def require_emb_chunks(state: ImportGraphState) -> list[dict]:
    '''
    校验需要的chunks
    :param state:
    :return:
    '''
    chunks = state.get('chunks')
    if not chunks or len(chunks) == 0:
        logger.error("chunks is empty 业务无法继续")
        raise ValueError("chunks is empty 业务无法继续")

    return chunks

@step_log('prepare_chunks_collection')
def prepare_chunks_collection():
    '''
    准备表名 schema index_params
    :return:
    '''
    # 1 获取客户端 和表名
    milvus_client = milvus_gateway.client
    chunks_collection = milvus_gateway.get_chunks_collection
    # 2 表名是否存在
    if milvus_client.has_collection(collection_name=chunks_collection):
        return
    # 3 schema 和 index_params
    schema = milvus_client.create_schema(auto_id=True, enable_dynamic_field=True)
    schema.add_field(
        field_name='chunk_id',
        datatype=DataType.INT64,
        is_primary=True
    )
    schema.add_field(
        field_name='content',
        datatype=DataType.VARCHAR,
        max_length=MILVUS_CHUNK_CONTENT_MAX_LENGTH
    )
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
        datatype=DataType.INT8
    )
    schema.add_field(
        field_name='dense_vector',
        datatype=DataType.FLOAT_VECTOR,
        dim=MILVUS_VECTOR_DIM
    )
    schema.add_field(
        field_name='sparse_vector',
        datatype=DataType.SPARSE_FLOAT_VECTOR,
    )
    index_params = milvus_client.prepare_index_params()
    index_params.add_index(
        field_name='dense_vector',
        index_type='HNSW',
        metric_type='COSINE',
        params={
            "M": 64,
            "efConstruction": 100
        }
    )
    index_params.add_index(
        field_name='sparse_vector',
        index_type='SPARSE_INVERTED_INDEX',
        metric_type='IP',
        params={
            "inverted_index_algo": "DAAT_MAXSCORE"
        }
    )
    # 4 创建表
    milvus_client.create_collection(
        collection_name=chunks_collection,
        schema=schema,
        index_params=index_params
    )
    res = milvus_client.list_collections()
    logger.info(f"库中集合有{res}")

@step_log('remove_old_chunks')
def remove_old_chunks(file_title: str):
    milvus_client = milvus_gateway.client
    chunks_collection = milvus_gateway.get_chunks_collection
    res = milvus_client.delete(
        collection_name=chunks_collection,
        filter=f'file_title=="{file_title}"'
    )
    logger.info(f'删除数据 结果是: {res}')

@step_log('insert_chunks')
def insert_chunks(chunks:list[dict]):
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
    入库服务：
    1. 准备集合 schema 和索引
    2. 根据 file_title 删除旧数据
    3. 批量插入新的 chunks
    4. 回写 chunk_id 等入库结果
    """
    # 1校验数据
    chunks = require_emb_chunks(state)
    # 2 准备创建表
    prepare_chunks_collection()
    # 3 删除旧数据 批量插入新数据
    file_title = state.get('file_title', '')
    remove_old_chunks(file_title)
    insert_chunks(chunks)
    return state
