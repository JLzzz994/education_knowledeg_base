from langchain_openai import ChatOpenAI

from app.infra.config.providers import infra_config
from app.shared.model import get_llm_client, get_bge_m3_ef, generate_embeddings, get_reranker_model


class LLMProvider:
    # 获取chat 文本模型 参数 模型名字 JSON_Mode
    def chat(self, model_name: str | None = None, json_mode: bool = False):
        return get_llm_client(model_name, json_mode)

    # 获取vision_chat 视觉模型
    def vision_chat(self, model_name: str | None = None):
        model_name = model_name or infra_config.llm.lv_model
        return get_llm_client(model_name)

    @property
    def embed_model(self):
        return get_bge_m3_ef()

    def embed_documents(self, documents: list[str]) -> dict[str, list]:
        '''
            {
               dense: [[],[]],
               sparse: [{},{}]
            }
        :param documents:
        :return:
        '''
        return generate_embeddings(documents)

    @property
    def reranker_model(self):
        return get_reranker_model()


llm_provider = LLMProvider()
