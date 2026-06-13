from app.process.import_.agent.state import ImportGraphState


def split_document(state: ImportGraphState) -> ImportGraphState:
    '''
    `md_content`, `file_title`
    `chunks`
    标题粗切 → 超长细切 → 超短合并
        文档切分服务：
    1. 按标题层级做一级粗切
    2. 对超长文本做二次细切
    3. 构造 chunks 列表
    4. 回写 chunks
    :param state:
    :return:
    '''
    return state