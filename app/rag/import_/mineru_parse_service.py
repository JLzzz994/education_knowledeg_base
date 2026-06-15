"""
MinerU 云端解析服务模块
支持 MinerU 可处理的所有文件格式：PDF、Word(.docx)、PPT(.pptx)、Excel(.xlsx)、图片、HTML
通过 MinerU API 将文件上传至云端解析，轮询结果，下载并解压获取 Markdown 文件

核心流程（三步）：
  1. 申请上传地址：POST /file-urls/batch → 获取 batch_id + upload_url
  2. 上传文件：PUT upload_url → 上传文件字节流
  3. 轮询结果：GET /extract-results/batch/{batch_id} → 直到 state=="done"，获取 full_zip_url
  4. 下载解压：下载 ZIP → 解压 → 提取 .md 文件

所有函数通过 state 字典传递数据，写入 md_content 和 md_path 供下游节点使用
"""
import shutil
import time
from pathlib import Path

import requests

from app.infra.config.providers import infra_config
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.config import (
    MINERU_MODEL_VERSION,
    MINERU_DOWNLOAD_TIMEOUT_SECONDS,
    MINERU_POLL_TIMEOUT_SECONDS,
    MINERU_POLL_INTERVAL_SECONDS,
)
from app.shared.runtime.logger import logger, step_log
from app.shared.utils.path_util import PROJECT_ROOT


@step_log('validate_file_path')
def validate_file_path(state: ImportGraphState) -> tuple[Path, Path, str]:
    """
    校验输入文件路径和输出目录
    :param state: 导入管线状态，需包含 source_file_path、local_dir、file_type 字段
    :return: (source_file_path_obj, local_dir_obj, file_type) 三元组
    :raises ValueError: source_file_path 为空
    :raises FileNotFoundError: 源文件不存在
    """
    # 1. 从 state 读取必要字段
    source_file_path = state.get('source_file_path')
    local_dir = state.get('local_dir')
    file_type = state.get('file_type')

    # 2. 校验源文件路径非空
    if not source_file_path:
        logger.error(f'source_file_path 为空，无法继续解析')
        raise ValueError(f'source_file_path 为空，无法继续解析')

    # 3. local_dir 为空时使用默认输出目录
    if not local_dir:
        logger.warning(f'local_dir 为空，将使用默认输出目录: /output')
        local_dir = PROJECT_ROOT / 'output'

    source_file_path_obj, local_dir_obj = Path(source_file_path), Path(local_dir)

    # 4. 校验源文件是否存在
    if not source_file_path_obj.is_file():
        logger.error(f'{file_type} 文件不存在: {source_file_path}')
        raise FileNotFoundError(f'{file_type} 文件不存在: {source_file_path}')

    # 5. 创建中间文件输出目录（递归创建）
    local_dir_obj.mkdir(parents=True, exist_ok=True)

    return source_file_path_obj, local_dir_obj, file_type


@step_log('upload_file_to_mineru')
def upload_file_to_mineru(source_file_path_obj: Path) -> str:
    """
    上传文件到 MinerU 云端并轮询解析结果，返回下载链接
    支持 MinerU 可处理的所有格式（PDF/DOCX/PPTX/XLSX/图片/HTML）

    流程：
      1. 校验 MinerU 配置（base_url、api_key）
      2. POST /file-urls/batch → 获取 batch_id 和上传 URL
      3. PUT 上传 URL → 上传文件字节流
      4. 轮询 GET /extract-results/batch/{batch_id} → 直到 state=="done"
      5. 返回 full_zip_url（解析结果 ZIP 的下载链接）

    :param source_file_path_obj: 源文件的 Path 对象
    :return: MinerU 解析结果 ZIP 的下载 URL
    :raises ValueError: MinerU 配置不完整
    :raises RuntimeError: API 调用失败或解析失败
    :raises TimeoutError: 轮询超时
    """
    # ==================== 第一步：校验 MinerU 配置 ====================
    if not infra_config.mineru.base_url or not infra_config.mineru.api_key:
        logger.error(f'MinerU 配置不完整，请检查 base_url 和 api_key')
        raise ValueError(f'MinerU 配置不完整，请检查 base_url 和 api_key')

    # ==================== 第二步：申请上传地址 ====================
    token = infra_config.mineru.api_key
    url = f'{infra_config.mineru.base_url}/file-urls/batch'
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    # 请求体：files 列表（含文件名）+ 模型版本
    data = {
        "files": [
            {"name": f"{source_file_path_obj.name}"}
        ],
        "model_version": MINERU_MODEL_VERSION
    }
    try:
        url_response = requests.post(url, headers=headers, json=data, timeout=MINERU_DOWNLOAD_TIMEOUT_SECONDS)

        # 响应示例：
        # {
        #   "code": 0,
        #   "data": {
        #     "batch_id": "2bb2f0ec-a336-4a0a-b61a-241afaf9cc87",
        #     "file_urls": ["https://..."]
        #   },
        #   "msg": "ok",
        #   "trace_id": "..."
        # }
        if url_response.status_code != 200:
            logger.error(f'获取上传 URL 失败，HTTP 状态码: {url_response.status_code}')
            raise RuntimeError(f'获取上传 URL 失败，HTTP 状态码: {url_response.status_code}')

        url_response_dict = url_response.json()
        code = url_response_dict.get('code')
        if code != 0:
            logger.error(f'获取上传 URL 业务异常，code={code}，msg={url_response_dict.get("msg")}')
            raise RuntimeError(f'获取上传 URL 业务异常，code={code}，msg={url_response_dict.get("msg")}')

        batch_id = url_response_dict.get('data', {}).get('batch_id')
        upload_file_url = url_response_dict.get('data', {}).get('file_urls')[0]
        logger.info(f'获取上传 URL 成功，batch_id={batch_id}，upload_file_url={upload_file_url}')
    except Exception as e:
        logger.exception(f'获取上传 URL 时发生异常')
        raise e

    # ==================== 第三步：上传文件字节流 ====================
    try:
        with requests.Session() as session:
            session.trust_env = False  # 不使用系统代理
            put_response = session.put(url=upload_file_url, data=source_file_path_obj.read_bytes())

            if (status_code := put_response.status_code) != 200:
                logger.error(f'上传文件失败，HTTP 状态码: {status_code}')
                raise RuntimeError(f'上传文件失败，HTTP 状态码: {status_code}')
    except Exception as e:
        logger.exception(f'上传文件 {source_file_path_obj.name} 时发生异常: {str(e)}')
        raise e

    # ==================== 第四步：轮询解析结果 ====================
    poll_url = f"{infra_config.mineru.base_url}/extract-results/batch/{batch_id}"
    poll_timeout = MINERU_POLL_TIMEOUT_SECONDS  # 最大等待时间（秒）
    poll_interval_time = MINERU_POLL_INTERVAL_SECONDS  # 轮询间隔（秒）
    start_time = time.time()

    while True:
        # 4.1 检查是否超时
        if (poll_total_time := (time.time() - start_time)) >= poll_timeout:
            logger.error(f'轮询解析结果超时，batch_id={batch_id}，已等待 {poll_total_time:.0f}s')
            raise TimeoutError(f'轮询解析结果超时，batch_id={batch_id}，已等待 {poll_total_time:.0f}s')

        # 4.2 发起轮询请求
        # 响应示例：
        # {
        #   "code": 0,
        #   "data": {
        #     "batch_id": "...",
        #     "extract_result": [{
        #       "file_name": "example.pdf",
        #       "state": "done",
        #       "err_msg": "",
        #       "full_zip_url": "https://..."
        #     }]
        #   },
        #   "msg": "ok"
        # }
        try:
            poll_response = requests.get(url=poll_url, headers=headers)
        except Exception as e:
            logger.warning(f'轮询请求网络异常，等待 {poll_interval_time}s 后重试')
            time.sleep(poll_interval_time)
            continue

        # 4.3 处理 HTTP 状态码
        if (poll_status_code := poll_response.status_code) != 200:
            if 500 <= poll_status_code < 600:
                # 服务器错误，等待后重试
                logger.warning(f'轮询时服务器返回 {poll_status_code}，等待 {poll_interval_time + 2}s 后重试')
                time.sleep(poll_interval_time + 2)
                continue
            logger.error(f'轮询时服务器返回 {poll_status_code}，业务无法继续')
            raise RuntimeError(f'轮询时服务器返回 {poll_status_code}，业务无法继续')

        # 4.4 处理业务状态码
        poll_response_dict = poll_response.json()
        msg = poll_response_dict.get('msg', '')
        if (poll_code := poll_response_dict.get('code')) != 0:
            logger.error(f'轮询业务异常，code={poll_code}，msg={msg}')
            raise RuntimeError(f'轮询业务异常，code={poll_code}，msg={msg}')

        # 4.5 检查解析状态
        poll_result_dict = poll_response_dict.get('data', {}).get('extract_result', [])[0]
        poll_state = poll_result_dict.get('state', 'failed')

        if poll_state == 'done':
            # 解析完成，返回下载 URL
            download_url = poll_result_dict.get('full_zip_url')
            if not download_url:
                logger.error(f'解析完成但下载 URL 为空')
                raise RuntimeError(f'解析完成但下载 URL 为空')
            return download_url

        if poll_state == 'failed':
            logger.error(f'文件解析失败，err_msg={poll_result_dict.get("err_msg", "")}')
            raise RuntimeError(f'文件解析失败，err_msg={poll_result_dict.get("err_msg", "")}')

        # 解析仍在进行中，等待后继续轮询
        logger.warning(f'{source_file_path_obj.name} 解析中，已等待 {poll_total_time:.0f}s，继续等待...')
        time.sleep(poll_interval_time)


@step_log('download_and_extract_md')
def download_and_extract_md(download_url, local_dir_obj: Path, stem: str) -> Path:
    """
    下载 MinerU 解析结果 ZIP 并提取 Markdown 文件
    :param download_url: ZIP 文件下载链接
    :param local_dir_obj: 本地输出目录
    :param stem: 文件名（不含后缀），用于命名解压目录和最终 MD 文件
    :return: 提取到的 .md 文件 Path 对象
    :raises RuntimeError: 下载失败或解压后无 MD 文件
    """
    # 1. 下载 ZIP 文件
    download_response = requests.get(download_url, timeout=MINERU_DOWNLOAD_TIMEOUT_SECONDS)
    if (download_status_code := download_response.status_code) != 200:
        logger.error(f'下载解析结果失败，URL={download_url}，状态码={download_status_code}')
        raise RuntimeError(f'下载解析结果失败，URL={download_url}，状态码={download_status_code}')

    # 2. 保存 ZIP 到本地
    download_path_obj = local_dir_obj / f'{stem}_result.zip'
    download_path_obj.write_bytes(download_response.content)

    # 3. 清理并重建解压目录
    unpack_path_obj = local_dir_obj / stem
    if unpack_path_obj.is_dir():
        shutil.rmtree(unpack_path_obj)
    unpack_path_obj.mkdir(parents=True, exist_ok=True)

    # 4. 解压 ZIP
    shutil.unpack_archive(download_path_obj, unpack_path_obj)

    # 5. 提取所有 .md 文件
    md_path_obj_list = list(unpack_path_obj.rglob(f'*.md'))
    if not md_path_obj_list:
        logger.error(f'解压后未找到任何 .md 文件，解压目录={unpack_path_obj}')
        raise RuntimeError(f'解压后未找到任何 .md 文件，解压目录={unpack_path_obj}')

    # 6. 选择最佳 .md 文件（优先级：同名 > full.md > 第一个）
    for md_path_obj in md_path_obj_list:
        if md_path_obj.stem == stem:
            logger.info(f'找到与源文件同名的 MD 文件: {md_path_obj.name}')
            return md_path_obj

    for md_path_obj in md_path_obj_list:
        if md_path_obj.stem.lower() == 'full':
            logger.info(f'找到 full.md 文件，重命名为 {stem}.md')
            return md_path_obj.rename(md_path_obj.with_name(f'{stem}.md'))

    # 兜底：使用第一个 .md 文件
    fallback = md_path_obj_list[0]
    logger.info(f'使用兜底 MD 文件: {fallback.name}，重命名为 {stem}.md')
    return fallback.rename(fallback.with_name(f'{stem}.md'))


@step_log('parse_file_to_markdown')
def parse_file_to_markdown(state: ImportGraphState) -> ImportGraphState:
    """
    将文件解析为 Markdown 的编排函数（支持 MinerU 可处理的所有格式）
    流程：校验文件 → 上传 MinerU → 下载解压 → 写入 state

    读取 state: source_file_path, local_dir, file_type
    写入 state: md_content（Markdown 正文）, md_path（MD 文件路径）

    :param state: 导入管线状态
    :return: 更新后的 state
    """
    # 1. 校验文件路径和输出目录
    source_file_path_obj, local_dir_obj, file_type = validate_file_path(state)

    # 2. 上传文件到 MinerU 云端解析
    download_url = upload_file_to_mineru(source_file_path_obj)

    # 3. 下载解析结果并提取 MD 文件
    md_path_obj = download_and_extract_md(download_url, local_dir_obj, source_file_path_obj.stem)

    # 4. 将 MD 内容和路径写入 state
    state['md_content'] = md_path_obj.read_text(encoding='utf-8')
    state['md_path'] = str(md_path_obj)

    return state
