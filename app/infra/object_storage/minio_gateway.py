from minio import Minio

from app.infra.config.providers import infra_config
from app.shared.clients import get_minio_client


class MinioGateway:
    '''
        Minio 对象存储网关类
        统一封装 MinIO客户端获取、配置读取、图片URL拼接等能力
        供全项目统一调用，避免到处写配置，重复拼接URL
    '''

    # 属性 获取MinIO存储桶名称(从全局配置读取)
    @property
    def bucket_name(self) -> str:
        return infra_config.minio.bucket_name

    # 获取MinIO中存放图片的目录路径(从全局配置读取) MINIO_IMG_DIR=/upload-images
    @property
    def image_dir(self) -> str:
        return infra_config.minio.minio_img_dir

    # 获取MinIO客户端实例,用于上传、下载、查询文件等操作
    @property
    def client(self) -> Minio:
        return get_minio_client()

    def build_image_url(self, stem: str, image_name: str) -> str:
        '''
        拼接生成MinIO 图片可访问URL(HTTP/HTTPS)
        :param stem: 文档名称(不带后缀) 用于区分不同文档的图片
        :param image_name: 图片原始文件名
        :return: 可直接访问的MinIO图片完整URL
        '''
        protocol = 'https' if infra_config.minio.minio_secure else 'http'
        return (f'{protocol}://{infra_config.minio.endpoint}/{self.bucket_name}{self.image_dir}/{stem}/{image_name}')

minio_gateway = MinioGateway()