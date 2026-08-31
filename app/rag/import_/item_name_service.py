"""
主体识别服务模块 - 通过 LLM 识别文档的核心产品/主体名称
职责：从 chunks 中提取上下文 → 调用 LLM 识别 item_name → 回填到 chunks → 向量化并写入 Milvus
item_name 用于后续查询时的主体匹配，是 RAG 检索的关键元数据
"""
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
    """
    校验 chunks 和 file_title 是否存在，file_title 为空时从 chunks 中兜底加载
    :param state: 导入管线状态
    :return: (chunks 列表, file_title 字符串)
    """
    # 1. 获取 chunks
    chunks = state.get('chunks')
    file_title = state.get('file_title')

    # 2. 校验 chunks 非空
    if not chunks:
        logger.error(f'chunks为空')
        raise ValueError('chunks为空')

    # 3. file_title 为空时，从第一个 chunk 中兜底获取
    if not file_title:
        logger.warning(f"file_title为空,加载{chunks[0].get('file_title')}")
        file_title = chunks[0].get('file_title') or 'default_file_title'
        state['file_title'] = file_title

    return chunks, file_title


@step_log('build_document_context')
def build_document_context(chunks: list[dict]) -> str:
    """
    从 chunks 中提取前 K 个切片，拼接为 LLM 上下文文本
    上下文格式："切片{i}标题:{title}父标题:{parent_title} 内容:{content} \n"
    :param chunks: chunk 列表
    :return: 截断后的上下文字符串（不超过 ITEM_NAME_CONTEXT_TOTAL_MAX_CHARS）
    """
    # 1. 取前 K 个切片（K = ITEM_NAME_CONTEXT_CHUNK_K）
    top_chunk = chunks[:ITEM_NAME_CONTEXT_CHUNK_K]

    # 2. 拼接每个切片的标题、父标题、内容
    context = ''
    for index, chunk in enumerate(top_chunk):
        context += f"切片{index}标题:{chunk.get('title')}父标题:{chunk.get('parent_title')} 内容:{chunk.get('content')} \n"

    # 3. 截断到最大长度，防止超出 LLM 上下文窗口
    final_context = context[:ITEM_NAME_CONTEXT_TOTAL_MAX_CHARS]
    return final_context


@step_log('recognize_item_name')
def recognize_item_name(item_context: str, file_title: str) -> str:
    """
    调用 LLM 识别文档的主体名称（产品名/设备名等）
    :param item_context: 拼接后的文档上下文
    :param file_title: 文件标题（作为 LLM 输出为空时的兜底值）
    :return: 识别到的主体名称
    """
    # 1. 获取 Chat 模型
    chat_model = llm_provider.chat()

    # 2. 加载系统提示词和用户提示词模板
    system_prompt = load_prompt('product_recognition_system')
    human_prompt = load_prompt('item_name_recognition', file_title=file_title, context=item_context)

    # 3. 组装消息列表
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    # 4. 构建链并调用 LLM
    chains = chat_model | StrOutputParser()
    item_name = chains.invoke(messages)
    logger.info(f'模型对主体识别完成,item_name:{item_name}')

    # 5. 空值兜底：LLM 返回空时使用 file_title 作为默认值
    if not item_name:
        item_name = file_title

    return item_name


@step_log('apply_item_name')
def apply_item_name(chunks: list[dict], item_name: str):
    """
    将识别到的 item_name 回填到每个 chunk 中
    :param chunks: chunk 列表
    :param item_name: 识别到的主体名称
    """
    for chunk in chunks:
        chunk['item_name'] = item_name


@step_log('embed_item_name')
def embed_item_name(item_name: str) -> tuple[list[float], dict[int, float]]:
    """
    对 item_name 进行向量化，生成稠密向量和稀疏向量
    :param item_name: 主体名称文本
    :return: (dense_vector, sparse_vector) 元组
    """
    result = llm_provider.embed_documents([item_name])
    logger.info(f'向量化完成,item_name:{result}')
    return result['dense'][0], result['sparse'][0]


@step_log('prepare_item_name_collection')
def prepare_item_name_collection():
    """
    准备 Milvus 中的 item_name 集合：若不存在则创建
    集合字段：pk(PK)、file_title、item_name、dense_vector、sparse_vector
    """
    # 1. 获取客户端和集合名
    client = milvus_gateway.client
    item_name_collection = milvus_gateway.get_item_name_collection

    # 2. 集合已存在则跳过
    if client.has_collection(collection_name=item_name_collection):
        return

    # 3. 定义 schema
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

    # 4. 定义索引参数
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

    # 5. 创建集合
    res = client.create_collection(
        collection_name=item_name_collection,
        schema=schema,
        index_params=index_params
    )


@step_log('upsert_item_name')
def upsert_item_name(file_title: str, item_name: str, dense: list[float], sparse: dict[int, float]):
    """
    将 item_name 写入 Milvus（先删后插，保证幂等）
    :param file_title: 文件标题（作为删除和关联的 key）
    :param item_name: 主体名称
    :param dense: 稠密向量
    :param sparse: 稀疏向量
    """
    # 1. 获取客户端
    milvus_client = milvus_gateway.client

    # 2. 确保集合存在
    prepare_item_name_collection()

    # 3. 删除该 file_title 的旧记录（幂等操作）
    milvus_client.delete(
        collection_name=milvus_gateway.get_item_name_collection,
        filter=f'file_title=="{file_title}"',
    )

    # 4. 插入新记录
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
    主体识别服务主入口，完整流程：
    1. 校验 chunks 和 file_title
    2. 从 chunks 构建文档上下文
    3. 调用 LLM 识别 item_name
    4. 将 item_name 回填到所有 chunks
    5. 对 item_name 进行向量化
    6. 准备 Milvus 集合
    7. 将 item_name 写入 Milvus
    8. 更新 state
    """
    # 1. 参数校验
    chunks, file_title = validate_chunks_title(state)
    # 2. 构造上下文
    item_context = build_document_context(chunks)
    # 3. LLM 识别主体名称
    item_name = recognize_item_name(item_context, file_title)
    # 4. 回填到所有 chunks
    apply_item_name(chunks, item_name)
    # 5. 生成向量
    dense, sparse = embed_item_name(item_name)
    # 6. 准备集合
    prepare_item_name_collection()
    # 7. 入库
    upsert_item_name(file_title, item_name, dense, sparse)
    # 8. 更新状态
    state['item_name'] = item_name
    state['chunks'] = chunks
    return state
