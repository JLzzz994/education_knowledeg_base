from langgraph.constants import END
from langgraph.graph import StateGraph

from app.process.import_.agent.nodes.node_bge_embedding import node_bge_embedding
from app.process.import_.agent.nodes.node_document_split import node_document_split
from app.process.import_.agent.nodes.node_entry import node_entry
from app.process.import_.agent.nodes.node_import_milvus import node_import_milvus
from app.process.import_.agent.nodes.node_item_name_recognition import node_item_name_recognition
from app.process.import_.agent.nodes.node_md_img import node_md_img
from app.process.import_.agent.nodes.node_pdf_to_md import node_pdf_to_md
from app.process.import_.agent.state import ImportGraphState
from app.shared.runtime.logger import logger

# noinspection PyTypeChecker
builder = StateGraph(ImportGraphState)

# noinspection PyTypeChecker
builder.add_node('node_entry', node_entry)
builder.add_node('node_pdf_to_md', node_pdf_to_md)
builder.add_node('node_md_img', node_md_img)
builder.add_node('node_document_split', node_document_split)
builder.add_node('node_item_name_recognition', node_item_name_recognition)
builder.add_node('node_bge_embedding', node_bge_embedding)
builder.add_node('node_import_milvus', node_import_milvus)


def node_entry_after(state: ImportGraphState):
    '''

    :param state:
    :return:
    '''
    file_type = state.get('file_type')
    local_file_path = state.get("local_file_path")

    if file_type == 'pdf':
        logger.info(f'判断文件{local_file_path}类型为{file_type},跳转node_pdf_to_md')
        return 'node_pdf_to_md'
    elif file_type == 'md':
        logger.info(f'判断文件{local_file_path}类型为{file_type},node_md_img')
        return 'node_md_img'
    else:
        logger.info(f'判断文件{local_file_path}类型不支持,跳转END')
        return END


builder.set_entry_point('node_entry')
builder.add_conditional_edges('node_entry', node_entry_after, {
    'node_pdf_to_md': 'node_pdf_to_md',
    'node_md_img': 'node_md_img',
    END: END
})
builder.add_edge('node_pdf_to_md', 'node_md_img')
builder.add_edge('node_md_img', 'node_document_split')
builder.add_edge('node_document_split', 'node_item_name_recognition')
builder.add_edge('node_item_name_recognition', 'node_bge_embedding')
builder.add_edge('node_bge_embedding', 'node_import_milvus')

import_graph_app = builder.compile()
