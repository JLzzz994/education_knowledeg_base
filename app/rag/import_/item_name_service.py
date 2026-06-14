from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from pymilvus import DataType

from app.infra.vectorstore.milvus_gateway import milvus_gateway
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.config import ITEM_NAME_CONTEXT_CHUNK_K, ITEM_NAME_CONTEXT_TOTAL_MAX_CHARS, \
    MILVUS_DEFAULT_VARCHAR_MAX_LENGTH, MILVUS_VECTOR_DIM
from app.shared.runtime.load_prompt import load_prompt
from app.shared.runtime.logger import logger, step_log
from app.infra.llm.providers import llm_provider
from app.shared.utils.escape_milvus_string_utils import escape_milvus_string


@step_log('validate_chunks_title')
def validate_chunks_title(state: ImportGraphState) -> tuple[list[dict], str]:
    '''
    获取本节点要使用的数据 校验空值
    :param state:
    :return:
    '''
    # 1 参数校验
    chunks = state.get('chunks')
    file_title = state.get('file_title')
    if not chunks:
        logger.error(f'chunks为空')
        raise ValueError('chunks为空')
    if not file_title:
        logger.warning(f"file_title为空,加载{chunks[0].get('file_title')}")
        file_title = chunks[0].get('file_title') or 'default_file_title'
        state['file_title'] = file_title
    return chunks, file_title


@step_log('build_document_context')
def build_document_context(chunks: list[dict]) -> str:
    '''
    上下文拼接 取前5个 拼接上下文 切片 1.标题: x 父标题: x 内容: x \n 最大字符串长度限制
    :param chunks:
    :return:
    '''
    top_chunk = chunks[:ITEM_NAME_CONTEXT_CHUNK_K]
    context = ''
    for index, chunk in enumerate(top_chunk):
        context += f"切片{index}标题:{chunk.get('title')}父标题:{chunk.get('parent_title')} 内容:{chunk.get('content')} \n"
    final_context = context[:ITEM_NAME_CONTEXT_TOTAL_MAX_CHARS]
    return final_context


@step_log('recognize_item_name')
def recognize_item_name(item_context: str, file_title: str) -> str:
    # 1 获取模型
    chat_model = llm_provider.chat()
    # 2 加载提示词
    system_prompt = load_prompt('product_recognition_system')
    human_prompt = load_prompt('item_name_recognition', file_title=file_title, context=item_context)
    # 3 组装messages
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]
    # 4 组链 调用  整个项目主要以使用学到的技术为主，不少人为创造的技术点或许并不符合实际需求
    chains = chat_model | StrOutputParser()
    item_name = chains.invoke(messages)
    # 这里因为与外界交互 容易出问题 所以这里加个日志
    logger.info(f'模型对主体识别完成,item_name:{item_name}')
    # 5 空值处理 给默认值
    if not item_name:
        item_name = file_title

    return item_name


@step_log('apply_item_name')
def apply_item_name(chunks: list[dict], item_name: str):
    '''
    回填item_name
    :param chunks:
    :param item_name:
    :return:
    '''
    for chunk in chunks:
        chunk['item_name'] = item_name


@step_log('embed_item_name')
def embed_item_name(item_name: str) -> tuple[list[float], dict[int, float]]:
    '''
    通过M3获得item_name对应的稠密向量和稀疏向量
    :param item_name:
    :return:  稠密向量和稀疏向量
    '''
    result = llm_provider.embed_documents([item_name])
    logger.info(f'向量化完成,item_name:{result}')
    return result['dense'][0], result['sparse'][0]


@step_log('prepare_item_name_collection')
def prepare_item_name_collection():
    '''
    创建存item_name的collection
    :return:
    '''
    # 1 获取客户端
    client = milvus_gateway.client
    # 2 获取集合名
    item_name_collection = milvus_gateway.get_item_name_collection
    # 3 检查集合是否已经存在
    if client.has_collection(collection_name=item_name_collection):
        return
    # 4 创建字段 和 索引
    schema = client.create_schema(enable_dynamic_field=True)
    schema.add_field(
        field_name='pk',
        datatype=DataType.INT64,
        auto_id=True,
        is_primary=True
    ).add_field(
        field_name='file_title',
        datatype=DataType.VARCHAR,
        max_length=MILVUS_DEFAULT_VARCHAR_MAX_LENGTH
    ).add_field(
        field_name='item_name',
        datatype=DataType.VARCHAR,
        max_length=MILVUS_DEFAULT_VARCHAR_MAX_LENGTH
    ).add_field(
        field_name='dense_vector',
        datatype=DataType.FLOAT_VECTOR,
        dim=MILVUS_VECTOR_DIM
    ).add_field(
        field_name='sparse_vector',
        datatype=DataType.SPARSE_FLOAT_VECTOR
    )
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name='dense_vector',
        index_type='HNSW',
        index_name='dense_vector_index',
        metric_type='COSINE',
        params={
            "M": 64,
            "efConstruction": 100
        }
    )
    index_params.add_index(
        field_name='sparse_vector',
        index_type='SPARSE_INVERTED_INDEX',
        index_name='sparse_vector_index',
        metric_type='IP',
        params={'inverted_index_algo': 'DAAT_MAXSCORE'}
    )
    res =client.create_collection(
        collection_name=item_name_collection,
        schema=schema,
        index_params=index_params
    )

@step_log('upsert_item_name')
def upsert_item_name(file_title: str, item_name: str, dense: list[float], sparse: dict[int, float]):
    '''
    先查后删最后插入 需要防注入 escape
    :param file_title:
    :param item_name:
    :param dense:
    :param sparse:
    :return:
    '''
    # 1 获取客户端
    milvus_client = milvus_gateway.client
    # 2 确保kb_item_names
    prepare_item_name_collection()
    # 3 查询记录 并删除

    milvus_client.delete(
        collection_name=milvus_gateway.get_item_name_collection,
        filter=f'file_title=="{file_title}"',
    )
    res = milvus_client.insert(
        collection_name=milvus_gateway.get_item_name_collection,
        data=[{
            'file_title': file_title,
            'item_name': item_name,
            'dense_vector': dense,
            'sparse_vector': sparse
        }]
    )
    logger.info(f'item_name入库完成,item_name:{item_name},res:{res}')


@step_log('recognize_and_index_item_name')
def recognize_and_index_item_name(state: ImportGraphState) -> ImportGraphState:
    """
    主体识别服务：
    1. 基于 chunks 构造上下文
    2. 调用 LLM 识别 item_name
    3. 将 item_name 回填到 state 和 chunks
    4. 同步写入主体名称索引
    """
    # 1 参数校验
    chunks, file_title = validate_chunks_title(state)
    # 2 构造上下文
    item_context = build_document_context(chunks)
    # 3 进行item_name识别
    item_name = recognize_item_name(item_context, file_title)
    # 4 回填到state
    apply_item_name(chunks, item_name)
    # 5 生成向量
    dense, sparse = embed_item_name(item_name)
    # 6 准备集合入库
    prepare_item_name_collection()
    # 7 item_name入库
    upsert_item_name(file_title, item_name, dense, sparse)
    # 更新状态
    state['item_name'] = item_name
    state['chunks'] = chunks
    return state
