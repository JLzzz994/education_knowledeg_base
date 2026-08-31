"""
导入管线全局配置模块
集中定义导入流程各阶段使用的常量，供所有导入服务统一引用
包括：文件类型支持、MinerU 解析参数、文本切块参数、Milvus 入库参数、主体识别参数
"""

# ==================== 文件类型配置 ====================
# 支持处理的文件类型集合，entry_service 用此判断是否可导入
# MinerU 支持: pdf, docx, pptx, xlsx, html, image
# 直接读取: md, txt
SUPPORTED_FILE_TYPES = {'pdf', 'md', 'txt', 'docx', 'pptx', 'xlsx', 'html', 'image'}

# 图片文件后缀集合，entry_service 用此将图片后缀统一映射为 file_type="image"
IMAGE_FILE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}

# ==================== 图片处理配置（enrich_markdown_images.py） ====================
# 图片上下文窗口长度：截取图片引用前后各多少字符作为视觉模型的上下文
CONTEXT_LENGTH = 100

# ==================== MinerU 云端解析配置（mineru_parse_service.py） ====================
# 支持格式: PDF、Word(.docx)、PPT(.pptx)、Excel(.xlsx)、图片、HTML
# MinerU 模型版本（vlm = 视觉语言模型，适合文档/图片高精度解析）
MINERU_MODEL_VERSION = "vlm"
# 轮询任务状态的最大超时时间（秒），一个 PDF 解析约等于 1 秒/页
MINERU_POLL_TIMEOUT_SECONDS = 600
# 轮询间隔时间（秒），每隔多久查询一次任务状态
MINERU_POLL_INTERVAL_SECONDS = 3
# 文件下载超时时间（秒），下载解析结果超过此时长则中断
MINERU_DOWNLOAD_TIMEOUT_SECONDS = 30

# ==================== 文本切块配置（split_service.py） ====================
# 单个文本块最大长度（字符），超过此长度会被二次拆分
CHUNK_MAX_SIZE = 1000
# 文本切块基准长度（字符），低于此长度的块会尝试与相邻块合并
CHUNK_SIZE = 600
# 相邻文本块重叠长度（字符），保证语义不被切断、上下文连贯
CHUNK_OVERLAP = 50

# ==================== 主体识别配置（item_name_service.py） ====================
# 构建上下文时取前 K 个切片作为 LLM 输入
ITEM_NAME_CONTEXT_CHUNK_K = 5
# 上下文最大字符数，超过则截断，防止超出 LLM 上下文窗口
ITEM_NAME_CONTEXT_TOTAL_MAX_CHARS = 10000

# ==================== 向量化配置（embedding_service.py） ====================
# BGE-M3 批量向化的批次大小，过大会占用过多显存
EMBEDDING_BATCH_SIZE = 5

# ==================== Milvus 字段配置（index_service.py / item_name_service.py） ====================
# VARCHAR 字段最大长度（用于 title、item_name、file_title 等短文本字段）
MILVUS_DEFAULT_VARCHAR_MAX_LENGTH = 512
# content 字段最大长度（用于存储长文本内容，需大于 CHUNK_MAX_SIZE）
MILVUS_CHUNK_CONTENT_MAX_LENGTH = 65535
# BGE-M3 稠密向量维度（模型固定输出 1024 维）
MILVUS_VECTOR_DIM = 1024

# ==================== 导入进度权重配置（import API 使用） ====================
# 各节点在导入流程中的权重百分比，用于计算整体进度
# 前端根据此权重展示进度条（REQ-05）
NODE_WEIGHTS = {
    "node_entry": 5,
    "node_pdf_to_md": 25,
    "node_docx_to_md": 25,    # Word → MD（MinerU 解析）
    "node_pptx_to_md": 25,    # PPT → MD（MinerU 解析）
    "node_xlsx_to_md": 25,    # Excel → MD（MinerU 解析）
    "node_image_ocr": 25,     # 图片 OCR（MinerU 解析）
    "node_html_to_md": 25,    # HTML → MD（MinerU 解析）
    "node_txt_to_md": 5,      # TXT 直接读取（无需云端解析，权重低）
    "node_md_img": 15,
    "node_document_split": 10,
    "node_item_name_recognition": 15,
    "node_bge_embedding": 20,
    "node_import_milvus": 10,
}
