from app.process.import_.agent.state import ImportGraphState


def enrich_markdown_images(state: ImportGraphState) -> ImportGraphState:
    """
    `md_path`, `md_content`
    `md_content`（替换图片 URL）
    扫描图片引用，视觉模型生成描述，上传 MinIO
    Markdown 图片增强服务：
    1. 扫描 Markdown 中的图片
    2. 调用多模态模型生成图片说明
    3. 上传图片到 MinIO
    4. 替换 Markdown 图片地址并回写 md_content

    """
    return state
