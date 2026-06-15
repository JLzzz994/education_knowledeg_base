"""
导入流程 LangGraph 图定义模块
构建多节点有向图，实现多格式文件从解析到 Milvus 入库的完整导入管线

支持格式（8 种）:
  MinerU 云端解析: PDF、Word(.docx)、PPT(.pptx)、Excel(.xlsx)、图片、HTML
  直接读取: Markdown(.md)、TXT(.txt)

图拓扑:
  node_entry ──(条件路由)──┬── node_pdf_to_md ────────┐
                           ├── node_docx_to_md ───────┤
                           ├── node_pptx_to_md ───────┤
                           ├── node_xlsx_to_md ───────┤
                           ├── node_image_ocr ────────┤
                           ├── node_html_to_md ───────┤
                           ├── node_txt_to_md ────────┤
                           ├── node_md_img ───────────┤（MD 直接走图片增强）
                           └── END(不支持/跳过)        │
                                                      ▼
                                          node_md_img（图片增强）
                                                      │
                                                      ▼
                                          node_document_split
                                                      │
                                                      ▼
                                      node_item_name_recognition
                                                      │
                                                      ▼
                                          node_bge_embedding
                                                      │
                                                      ▼
                                          node_import_milvus → END

REQ-15: 使用 FORMAT_HANDLER_MAP 实现可扩展的多格式路由
"""
from langgraph.constants import END
from langgraph.graph import StateGraph

from app.process.import_.agent.nodes.node_bge_embedding import node_bge_embedding
from app.process.import_.agent.nodes.node_document_split import node_document_split
from app.process.import_.agent.nodes.node_docx_to_md import node_docx_to_md
from app.process.import_.agent.nodes.node_entry import node_entry
from app.process.import_.agent.nodes.node_html_to_md import node_html_to_md
from app.process.import_.agent.nodes.node_image_ocr import node_image_ocr
from app.process.import_.agent.nodes.node_import_milvus import node_import_milvus
from app.process.import_.agent.nodes.node_item_name_recognition import node_item_name_recognition
from app.process.import_.agent.nodes.node_md_img import node_md_img
from app.process.import_.agent.nodes.node_pdf_to_md import node_pdf_to_md
from app.process.import_.agent.nodes.node_pptx_to_md import node_pptx_to_md
from app.process.import_.agent.nodes.node_txt_to_md import node_txt_to_md
from app.process.import_.agent.nodes.node_xlsx_to_md import node_xlsx_to_md
from app.process.import_.agent.state import ImportGraphState
from app.shared.runtime.logger import logger

# ==================== 格式处理器注册表（REQ-15） ====================
# 文件类型 → 处理节点名映射，新增格式只需在此添加一行即可扩展
# MinerU 支持的格式: pdf, docx, pptx, xlsx, html, image
# 直接读取的格式: md, txt
FORMAT_HANDLER_MAP = {
    "pdf": "node_pdf_to_md",       # PDF → MinerU 解析 → MD → 图片增强
    "md": "node_md_img",           # MD  → 直接读取 → 图片增强
    "docx": "node_docx_to_md",     # Word → MinerU 解析 → MD → 图片增强
    "pptx": "node_pptx_to_md",     # PPT → MinerU 解析 → MD → 图片增强
    "xlsx": "node_xlsx_to_md",     # Excel → MinerU 解析 → MD → 图片增强
    "image": "node_image_ocr",     # 图片 → MinerU OCR → MD → 图片增强
    "html": "node_html_to_md",     # HTML → MinerU 解析 → MD → 图片增强
    "txt": "node_txt_to_md",       # TXT → 直接读取 → MD → 图片增强
}

# ==================== 构建状态图 ====================
# noinspection PyTypeChecker
builder = StateGraph(ImportGraphState)

# ==================== 注册处理节点 ====================
# noinspection PyTypeChecker
builder.add_node('node_entry', node_entry)                              # 入口：文件类型识别 & 路由
builder.add_node('node_pdf_to_md', node_pdf_to_md)                      # PDF → MD（MinerU 云端解析）
builder.add_node('node_docx_to_md', node_docx_to_md)                    # Word → MD（MinerU 云端解析）
builder.add_node('node_pptx_to_md', node_pptx_to_md)                    # PPT → MD（MinerU 云端解析）
builder.add_node('node_xlsx_to_md', node_xlsx_to_md)                    # Excel → MD（MinerU 云端解析）
builder.add_node('node_image_ocr', node_image_ocr)                      # 图片 OCR（MinerU 云端解析）
builder.add_node('node_html_to_md', node_html_to_md)                    # HTML → MD（MinerU 云端解析）
builder.add_node('node_txt_to_md', node_txt_to_md)                      # TXT → MD（直接读取）
builder.add_node('node_md_img', node_md_img)                            # Markdown 图片增强（视觉模型 + MinIO）
builder.add_node('node_document_split', node_document_split)            # 文档切分（标题切 + 超长切 + 短块合并）
builder.add_node('node_item_name_recognition', node_item_name_recognition)  # 主体名称识别（LLM）
builder.add_node('node_bge_embedding', node_bge_embedding)              # 向量化（BGE-M3 稠密 + 稀疏）
builder.add_node('node_import_milvus', node_import_milvus)              # Milvus 入库（删除旧数据 + 写入新数据）


def node_entry_after(state: ImportGraphState):
    """
    条件路由函数（REQ-15 改造为动态路由）
    1. 检查 skip_import 标记（REQ-06 哈希命中时跳过）
    2. 从 FORMAT_HANDLER_MAP 查找文件类型对应的处理节点
    3. 未注册的类型 → END
    """
    file_type = state.get('file_type', '')
    local_file_path = state.get("local_file_path", "")

    # REQ-06: 哈希命中，跳过导入
    if state.get('skip_import'):
        logger.info(f'文件{local_file_path}哈希已存在,跳过导入')
        return END

    # REQ-15: 从注册表查找处理器
    handler = FORMAT_HANDLER_MAP.get(file_type)
    if handler:
        logger.info(f'判断文件{local_file_path}类型为{file_type},跳转{handler}')
        return handler

    logger.warning(f'判断文件{local_file_path}类型{file_type}不支持,跳转END')
    return END


# ==================== 图拓扑连接 ====================
builder.set_entry_point('node_entry')

# node_entry 之后的条件分支（动态路由 + END）
builder.add_conditional_edges('node_entry', node_entry_after, {
    **{v: v for v in FORMAT_HANDLER_MAP.values()},
    END: END,
})

# ==================== 图拓扑连接 ====================
# 所有格式处理节点 → node_md_img（图片增强） → 下游流程
builder.add_edge('node_pdf_to_md', 'node_md_img')
builder.add_edge('node_docx_to_md', 'node_md_img')
builder.add_edge('node_pptx_to_md', 'node_md_img')
builder.add_edge('node_xlsx_to_md', 'node_md_img')
builder.add_edge('node_image_ocr', 'node_md_img')
builder.add_edge('node_html_to_md', 'node_md_img')
builder.add_edge('node_txt_to_md', 'node_md_img')
builder.add_edge('node_md_img', 'node_document_split')
builder.add_edge('node_document_split', 'node_item_name_recognition')
builder.add_edge('node_item_name_recognition', 'node_bge_embedding')
builder.add_edge('node_bge_embedding', 'node_import_milvus')

# 编译为可执行的图应用
import_graph_app = builder.compile()


if __name__ == "__main__":
    from app.shared.utils.path_util import PROJECT_ROOT
    import os
    from app.shared.runtime.logger import logger

    # 全流程测试：验证PDF导入→Milvus入库完整链路
    logger.info("===== 开始执行知识图谱导入全流程测试 =====")

    # 1. 构造测试文件路径（复用你项目的doc目录）
    test_pdf_name = os.path.join("doc", "hak180产品安全手册.pdf")
    test_pdf_path = os.path.join(PROJECT_ROOT, test_pdf_name)

    # 2. 构造输出目录（存放MD/图片等中间文件）
    test_output_dir = os.path.join(PROJECT_ROOT, "output")
    os.makedirs(test_output_dir, exist_ok=True)  # 不存在则创建

    # 3. 校验测试PDF文件是否存在
    if not os.path.exists(test_pdf_path):
        logger.error(f"全流程测试失败：测试PDF文件不存在，路径：{test_pdf_path}")
        logger.info("请检查文件路径，或手动将测试文件放入项目根目录的doc文件夹中")
    else:
        # 4. 构造测试状态（贴合实际业务入参，开启PDF解析开关）
        test_state = ImportGraphState({
            "task_id": "test_kg_import_workflow_001",  # 测试任务ID
            "local_file_path": test_pdf_path,  # 测试PDF文件路径
            "local_dir": test_output_dir,  # 中间文件输出目录
        })
        try:
            logger.info(f"测试任务启动，PDF文件路径：{test_pdf_path}")
            logger.info(f"中间文件输出目录：{test_output_dir}")
            logger.info("开始执行全流程节点，依次执行：entry→pdf2md→md_img→split→item_name→embedding→milvus")

            # 5. 执行LangGraph全流程（流式执行，打印节点执行进度）
            final_state = None
            for step in import_graph_app.stream(test_state, stream_mode="values"):
                # 打印当前执行完成的节点（流式输出更直观）
                current_node = list(step.keys())[-1] if step else "未知节点"
                logger.info(f"✅ 节点执行完成：{current_node}")
                final_state = step  # 保存最终状态

            # 6. 全流程执行完成，结果预览和核心指标打印
            if final_state:
                logger.info("-" * 80)
                logger.info("===== 全流程测试执行成功，核心结果预览 =====")

                # 提取核心结果指标
                chunks = final_state.get("chunks", [])
                chunk_count = len(chunks)
                md_content = final_state.get("md_content", "")[:150]  # MD内容前150字符
                item_name = final_state.get("item_name", "未识别")  # 主体名称
                has_embedding = all("dense_vector" in c and "sparse_vector" in c for c in chunks) if chunks else False
                has_chunk_id = all("chunk_id" in c for c in chunks) if chunks else False

                # 打印核心指标
                logger.info(f"📄 PDF转MD内容预览（前150字符）：{md_content}...")
                logger.info(f"🏷️  识别的主体名称：{item_name}")
                logger.info(f"📝 文档切分总切片数：{chunk_count}")
                logger.info(f"🔍 所有切片是否完成向量化：{'是' if has_embedding else '否'}")
                logger.info(f"🗄️  所有切片是否完成Milvus入库（含chunk_id）：{'是' if has_chunk_id else '否'}")
                logger.info(f"📂 最终状态包含的核心键：{list(final_state.keys())}")
                logger.info("-" * 80)
        except Exception as e:
            logger.exception(f"===== 全流程测试运行失败 =====")
    logger.info("===== 知识图谱导入全流程测试结束 =====")