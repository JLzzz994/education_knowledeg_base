import re
from pathlib import Path

import mimetypes
from langchain_core.output_parsers import StrOutputParser
from minio.deleteobjects import DeleteObject

from app.infra.llm.providers import llm_provider
from app.infra.object_storage.minio_gateway import minio_gateway
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.config import CONTEXT_LENGTH, SUPPORTED_IMAGE_EXTENSIONS
from app.shared.runtime.load_prompt import load_prompt
from app.shared.runtime.logger import logger, step_log


@step_log('load_md_and_images_path')
def load_md_and_images_path(state: ImportGraphState) -> tuple[str, Path, Path]:
    '''

    :param state:
    :return:
    '''
    source_file_path = state.get('source_file_path')
    md_content = state.get('md_content')
    file_type = state.get('file_type')
    # 如果上传文件本身是md 给md_path赋值
    if file_type == 'md':
        state['md_path'] = source_file_path
    md_path = state.get('md_path')

    if not md_path:
        logger.error('md_path为空,无法获取md文件和图片地址')
        raise ValueError('md_path为空,无法获取md文件和图片地址')
    md_path_obj = Path(md_path)
    if not md_content:
        logger.info('md_content没有内容,可能上传文件本身是md,根据md_path读取一下')
        md_content = md_path_obj.read_text(encoding='utf-8')
        if not md_content:
            logger.error('md_content没有内容,二次读取后仍然为空')
            raise ValueError('md_content没有内容,二次读取后仍然为空')
        state['md_content'] = md_content
    images_path_obj = md_path_obj.parent / 'images'
    return md_content, md_path_obj, images_path_obj

@step_log('scan_images_match_context')
def scan_images_match_context(md_content: str, images_path_obj: Path, context_length: int = CONTEXT_LENGTH) -> list[
    tuple[str, str, tuple[str, str]]]:
    '''
    获取图片的上下文  先遍历images_path_obj下的图片 通过图片名正则匹配md_content中的上下文
    :param md_content: md正文
    :param images_path_obj: 图片地址
    :param context_length: 上下文分别长度
    :return:(图片名.后缀,图片路径,(上文,下文))
    '''
    images_context = []
    # 2.1 从images_path_obj下获取每一张图片
    for image_file_obj in images_path_obj.iterdir():
        image_name = image_file_obj.name
        # 2.2 遍历文件 排除不支持的格式
        if not image_file_obj.suffix in SUPPORTED_IMAGE_EXTENSIONS:
            logger.warning(f'{image_name}不是支持的图片格式')
            continue

        # 2.3 定义图片的专属正则 ![]()
        reg = re.compile(r"\!\[.*?\]\(.*?" + re.escape(image_name) + r".*?\)")
        # 2.4 因为uuid有且仅有一张匹配
        match = reg.search(md_content)
        # 2.5 没找到,证明图片没有被引用 不需要识别上下文
        if not match:
            logger.warning(f'图片{image_name}没有被引用,跳过')
            continue
        # 2.6 匹配到 截取上下文
        start, end = match.span()
        pre_context = md_content[max(0, start - context_length):start]
        post_context = md_content[end:min(len(md_content), end + context_length)]

        images_context.append(
            (image_name, str(image_file_obj), (pre_context, post_context))
        )
    logger.info(f'图片识别完成,共{len(images_context)}张图片')
    return images_context

@step_log('summarize_image')
def summarize_image(images_context: list[tuple[str, str, tuple[str, str]]], image_name2url: dict[str, str],
                    file_name_stem: str) -> dict[str, str]:
    '''
    调用千问视觉模型 生成image_summary
    :param images_context:(图片名.后缀,本地地址(上文,下文))
    :param image_name2url:(image_name,minio_image_url)
    :param file_name_stem: 文件名
    :return:{item_name,image_summary}
    '''
    # 1 获取视觉模型
    vision_model = llm_provider.vision_chat()
    image_name2summary = {}
    # 2 组装提示词
    for image_name, image_path, (pre_context, post_context) in images_context:
        image_summary_prompt = load_prompt(name='image_summary', root_folder=file_name_stem,
                                           image_content=(pre_context, post_context))
        if not image_name2url.get(image_name):
            logger.warning(f'图片{image_name}没有找到对应的url')
            continue
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_name2url.get(image_name),
                        },
                    },
                    {"type": "text", "text": image_summary_prompt},
                ],
            },
        ]
        image_summary = (vision_model | StrOutputParser()).invoke(messages)
        # 图片名:图片总结
        image_name2summary[image_name] = image_summary
    logger.info(f'图片总结完成,共{len(image_name2summary)}张图片')
    return image_name2summary

@step_log('upload_images_and_replace_urls')
def upload_images_and_replace_urls(images_context: list[tuple[str, str, tuple[str, str]]], md_content: str,
                                   file_name_stem: str):
    '''
    上传minIO 替换md中的url 能获得文件名和url的字典 可以先不替换
    :param images_context:(图片名.后缀,本地地址(上文,下文))
    :param md_content:md正文
    ：:param file_name_stem
    :return:md_content
    '''
    # 1 上传minIO 获得图片名和url
    # 1.1 获取客户端
    client = minio_gateway.client
    # 1.2 查询删除的对象列表 Iterator[Object]
    list_object = client.list_objects(
        bucket_name=minio_gateway.bucket_name,  # knowledge-base-files-jlz
        prefix=f'{minio_gateway.image_dir[1:]}/{file_name_stem}',  # /upload-images /烫金机
        recursive=True
    )
    # Iterator[DeleteObject]
    delect_object_list = [DeleteObject(lo.object_name) for lo in list_object]
    errors = client.remove_objects(
        bucket_name=minio_gateway.bucket_name,
        delete_object_list=delect_object_list
    )
    for error in errors:
        logger.warning(f'删除文件出现异常{error}')
    logger.info(f'minIO删除文件名下对应的图片')

    # 1.3 批量上传图片
    image_name2url = {}
    for image_name, image_path, _ in images_context:
        try:
            object_name = f'{minio_gateway.image_dir}/{file_name_stem}/{image_name}'
            client.fput_object(
                bucket_name=minio_gateway.bucket_name,
                object_name=object_name,
                file_path=image_path,
                content_type=mimetypes.guess_type(image_name)[0]
            )
            image_name2url[image_name] = minio_gateway.build_image_url(file_name_stem, image_name)
        except Exception as e:
            logger.error(f'{image_name}图片上传失败,跳过继续上传,异常: {e}')
    # 1.4 获取image_summary_dict
    image_name2summary = summarize_image(images_context, image_name2url, file_name_stem)
    # 1.5 循环处理每张图片 替换md_content
    for image_name, image_summary in image_name2summary.items():
        image_url = image_name2url.get(image_name)
        reg = re.compile(r"\!\[.*?\]\(.*?" + re.escape(image_name) + r".*?\)")
        md_content = reg.sub(lambda _: f"![{image_summary}]({image_url})", md_content)
    return md_content

@step_log('backup_new_md_content')
def backup_new_md_content(md_content_new: str, md_path_obj: Path) -> str:
    '''
    备份 返回新路径
    :param md_content_new:
    :param md_path_obj:
    :return:
    '''
    md_path_obj_new = md_path_obj.with_name(f'{md_path_obj.stem}_new.md')
    md_path_obj_new.write_text(md_content_new, encoding='utf-8')
    return str(md_path_obj_new)

@step_log('enrich_markdown_images')
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
    # 1 获取要使用的参数 md_content, md_path_obj, images_path_obj
    md_content, md_path_obj, images_path_obj = load_md_and_images_path(state)
    # 2 判断image_path_obj 是否存在内容,没有,直接结束进行下一个节点(没有图片也一定有images)
    if not any(images_path_obj.iterdir()):
        logger.warning(f'当前{md_content}没有图片,无需图片处理 正常进入下一个节点')
        return state
    # 3 获取匹配图片的上下文
    images_context: list[tuple[str, str, tuple[str, str]]] = scan_images_match_context(md_content, images_path_obj)
    # 4 上传minIO 获得图片的总结 替换图片的总结
    md_content_new = upload_images_and_replace_urls(images_context, md_content, md_path_obj.stem)
    # 5 备份
    md_path_new = backup_new_md_content(md_content_new, md_path_obj)
    # 6 更新
    state['md_content'] = md_content_new
    state['md_path'] = md_path_new
    return state
