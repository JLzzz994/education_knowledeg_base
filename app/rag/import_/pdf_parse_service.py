import shutil
import time
from pathlib import Path

import requests

from app.infra.config.providers import infra_config
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.config import MINERU_MODEL_VERSION, MINERU_DOWNLOAD_TIMEOUT_SECONDS, MINERU_POLL_TIMEOUT_SECONDS, \
    MINERU_POLL_INTERVAL_SECONDS
from app.shared.runtime.logger import logger, step_log
from app.shared.utils.path_util import PROJECT_ROOT

@step_log('validate_pdf_path')
def validate_pdf_path(state: ImportGraphState) -> tuple[Path, Path, str]:
    '''
    source_file_path, local_dir
    :param state:
    :return:
    '''
    source_file_path = state.get('source_file_path')
    local_dir = state.get('local_dir')
    file_type = state.get('file_type')
    # 1 校验目录是否存在
    if not source_file_path:
        logger.error(f'source_file_path中pdf不存在,导入业务无法继续')
        raise ValueError(f'source_file_path中pdf不存在,导入业务无法继续')
    if not local_dir:
        logger.warning(f'校验local_dir为空,将使用默认输出目录: /output')
        local_dir = PROJECT_ROOT / 'output'
    source_file_path_obj, local_dir_obj = Path(source_file_path), Path(local_dir)
    # 2 校验文件是否存在
    if not source_file_path_obj.is_file():
        logger.error(f'{file_type}文件不存在')
        raise FileNotFoundError(f'{file_type}文件不存在')
    # 3 创建中间文件输出目录
    local_dir_obj.mkdir(parents=True, exist_ok=True)

    return source_file_path_obj, local_dir_obj, file_type

@step_log('upload_pdf_to_mineru')
def upload_pdf_to_mineru(source_file_path_obj: Path) -> str:
    '''

    :param source_file_path_obj:
    :return:
    '''
    # 1 校验MinerU配置是否完整
    if not infra_config.mineru.base_url or not infra_config.mineru.api_key:
        logger.error(f'MinerU配置不完整,请检查')
        raise ValueError(f'MinerU配置不完整,请检查')

    # 2 调用/file-urls/batch 申请上传地址与batch_id
    token = infra_config.mineru.api_key
    url = f'{infra_config.mineru.base_url}/file-urls/batch'
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    data = {
        "files": [
            {"name": f"{source_file_path_obj.name}"}
        ],
        "model_version": MINERU_MODEL_VERSION
    }
    try:
        url_response = requests.post(url, headers=headers, json=data, timeout=MINERU_DOWNLOAD_TIMEOUT_SECONDS)
        # {
        #   "code": 0,
        #   "data": {
        #     "batch_id": "2bb2f0ec-a336-4a0a-b61a-241afaf9cc87",
        #     "file_urls": ["https://***"]
        #   },
        #   "msg": "ok",
        #   "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
        # }
        if url_response.status_code != 200:
            logger.error(f'获取上传文件的url时,服务器异常,状态码为{url_response.status_code}')
            raise RuntimeError(f'获取上传文件的url时,服务器异常,状态码为{url_response.status_code}')
        url_response_dict = url_response.json()
        code = url_response_dict.get('code')
        if code != 0:
            logger.error(f'获取上传文件的url时,业务异常,业务状态码是{code},异常信息:{url_response_dict.get('msg')}')
            raise RuntimeError(
                f'获取上传文件的url时,业务异常,业务状态码是{code},异常信息:{url_response_dict.get('msg')}')

        batch_id = url_response_dict.get('data', {}).get('batch_id')
        upload_file_url = url_response_dict.get('data', {}).get('file_urls')[0]
        logger.info(f'获取上传文件的url成功 batch_id:{batch_id},upload_file_url:{upload_file_url}')
    except Exception as e:
        logger.exception(f'获取上传文件的url时,异常')
        raise e

    # 3 使用session 上传文件
    try:
        with requests.Session() as session:
            session.trust_env = False
            put_response = session.put(url=upload_file_url, data=source_file_path_obj.read_bytes())

            if (status_code := put_response.status_code) != 200:
                logger.error(f'使用session上传文件时,服务器异常,状态码为{status_code}')
                raise RuntimeError(f'使用session上传文件时,服务器异常,状态码为{status_code}')
    except Exception as e:
        logger.exception(f'上传文件{source_file_path_obj.name}发生异常{str(e)}')
        raise e
    '''

import requests

token = "API管理页面自定创建的token"
batch_id = "上一步批量提交返回的 batch_id"
url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}

res = requests.get(url, headers=header)
print(res.status_code)
print(res.json())
print(res.json()["data"])
'''
    # 4 获取下载链接
    poll_url = f"{infra_config.mineru.base_url}/extract-results/batch/{batch_id}"
    poll_timeout = MINERU_POLL_TIMEOUT_SECONDS  # 600
    poll_interval_time = MINERU_POLL_INTERVAL_SECONDS  # 5
    start_time = time.time()

    while True:
        # 4.1 判断是否超时
        if (poll_total_time := (time.time() - start_time)) >= poll_timeout:
            logger.error(f'轮询获取下载url超时,batch_id:{batch_id}用时{poll_total_time}')
            raise TimeoutError(f'轮询获取下载url超时,batch_id:{batch_id}用时{poll_total_time}')

        '''
            {
          "code": 0,
          "data": {
            "batch_id": "2bb2f0ec-a336-4a0a-b61a-241afaf9cc87",
            "extract_result": [
              {
                "file_name": "example.pdf",
                "state": "done",
                "err_msg": "",
                "full_zip_url": "https://cdn-mineru.openxlab.org.cn/pdf/018e53ad-d4f1-475d-b380-36bf24db9914.zip"
              },
              {
                "file_name": "demo.pdf",
                "state": "running",
                "err_msg": "",
                "extract_progress": {
                  "extracted_pages": 1,
                  "total_pages": 2,
                  "start_time": "2025-01-20 11:43:20"
                }
              }
            ]
          },
          "msg": "ok",
          "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
        }
        
        '''
        # 4.2 发起网络请求
        try:
            poll_response = requests.get(url=poll_url, headers=headers)
        except Exception as e:
            logger.warning(f'轮询获取下载url时,网络请求失败,等待后继续尝试')
            time.sleep(poll_interval_time)
            continue

        # 4.3 判断状态码
        if (poll_status_code := poll_response.status_code) != 200:
            if 500 <= poll_status_code < 600:
                logger.warning(f'轮询获取下载url时，服务器异常{poll_status_code},等待后继续尝试')
                time.sleep(poll_interval_time + 2)
                continue
            logger.error(f'轮询获取下载url时，服务器异常{poll_status_code},业务无法继续')
            raise RuntimeError(f'轮询获取下载url时，服务器异常{poll_status_code},业务无法继续')

        poll_response_dict = poll_response.json()
        msg = poll_response_dict.get('msg', '')
        if (poll_code := poll_response_dict.get('code')) != 0:
            logger.error(f'轮询获取下载url时,业务异常,业务状态码:{poll_code},业务异常信息:{msg}')
            raise RuntimeError(f'轮询获取下载url时,业务异常,业务状态码:{poll_code},业务异常信息:{msg}')

        poll_result_dict = poll_response_dict.get('data', {}).get('extract_result', [])[0]
        poll_state = poll_result_dict.get('state', 'failed')
        if poll_state == 'done':
            download_url = poll_result_dict.get('full_zip_url')
            if not download_url:
                logger.error(f'轮询获取下载url时,业务异常,下载url为空')
                raise RuntimeError(f'轮询获取下载url时,业务异常,下载url为空')
            return download_url
        if poll_state == 'failed':
            logger.error(f'轮询获取下载url时,业务异常,解析失败')
            raise RuntimeError(f'轮询获取下载url时,业务异常,解析失败')
        logger.warning(f'{source_file_path_obj.name}任务正在解析中... 请等待')
        time.sleep(poll_interval_time)

@step_log('download_and_extract_md')
def download_and_extract_md(download_url, local_dir_obj: Path, stem: str) -> Path:
    '''
    下载解析后的文件抽取md (解压-> 找md)
    :param download_url:
    :param local_dir_obj:
    :param stem:
    :param file_type:
    :return:
    '''
    # 1下载
    download_response = requests.get(download_url, timeout=MINERU_DOWNLOAD_TIMEOUT_SECONDS)
    if (download_status_code := download_response.status_code) != 200:
        logger.error(f'下载文件{stem}失败,下载地址:{download_url},响应码:{download_status_code}')
        raise RuntimeError(f'下载文件{stem}失败,下载地址:{download_url},响应码:{download_status_code}')
    # 2 保存到输出目录
    download_path_obj = local_dir_obj / f'{stem}_result.zip'
    download_path_obj.write_bytes(download_response.content)
    # 3 清理解压目录 并 解压
    unpack_path_obj = local_dir_obj / stem
    if unpack_path_obj.is_dir():
        shutil.rmtree(unpack_path_obj)
    unpack_path_obj.mkdir(parents=True, exist_ok=True)
    shutil.unpack_archive(download_path_obj, unpack_path_obj)

    # 4 提取文件夹中所有的.md文件
    md_path_obj_list = list(unpack_path_obj.rglob(f'*.md'))
    if not md_path_obj_list:
        logger.error('下载成功,解压后没有发现任何md文件')
        raise RuntimeError('下载成功,解压后没有发现任何md文件')

    for md_path_obj in md_path_obj_list:
        if md_path_obj.stem == stem:
            logger.info(f'解压名与文件名相同,不用处理')
            return md_path_obj
    full_md_path_obj = None
    for md_path_obj in md_path_obj_list:
        if md_path_obj.stem.lower() == 'full':
            full_md_path_obj = md_path_obj
            break
    # 找不到上面两种 兜底方案
    if not full_md_path_obj:
        full_md_path_obj = md_path_obj_list[0]

    logger.info(f'获得解压后的md文件名为,{full_md_path_obj} 重命名后:{stem}.md')
    return full_md_path_obj.rename(full_md_path_obj.with_name(f'{stem}.md'))

@step_log('parse_pdf_to_markdown')
def parse_pdf_to_markdown(state: ImportGraphState) -> ImportGraphState:
    '''
    source_file_path file_type file_title, `local_dir`
    `md_path`, `md_content`
    source_file_path md_content
    调用 MinerU 解析 PDF，下载解压结果
    :param state:
    :return:
    '''
    # 1 校验
    source_file_path_obj, local_dir_obj, file_type = validate_pdf_path(state)
    # 2 上传文件到minerU
    download_url = upload_pdf_to_mineru(source_file_path_obj)
    # 3 下载 解压 获得md文件
    md_path_obj = download_and_extract_md(download_url, local_dir_obj, source_file_path_obj.stem)
    # 4 更新
    state['md_content'] = md_path_obj.read_text(encoding='utf-8')
    state['md_path'] = str(md_path_obj)

    return state
