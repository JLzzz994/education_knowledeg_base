import re
from typing import Tuple, List

INJECTION_KEYWORDS = [
    "忽略之前的指令",
    "忘记你之前的角色",
    "现在你是",
    "你现在是",
    "忽略以上内容",
    "忽略所有指令",
    "忽略前面的话",
    "不要遵循",
    "不要执行",
    "违背指令",
    "覆盖指令",
    "作为一个",
    "扮演",
    "假设你是",
    "假装你是",
    "我命令你",
    "必须执行",
    "强制要求",
    "你需要",
    "请忽略",
    "无视规则",
    "绕过限制",
    "突破限制",
    "解除限制",
    "移除限制",
    "disable safety",
    "turn off safety",
    "ignore safety",
    "bypass filter",
    "override instructions",
    "ignore previous",
    "forget previous",
    "ignore all",
    "role play",
    "act as",
    "behave as",
    "simulate being",
    "system prompt",
    "modify system",
    "change system",
]

def detect_prompt_injection(query: str) -> Tuple[bool, List[str]]:
    """
    检测用户输入中是否存在提示词注入攻击
    
    :param query: 用户输入的问题
    :return: (是否检测到攻击, 匹配的攻击模式列表)
    """
    matched_patterns = []
    query_lower = query.lower()
    
    for keyword in INJECTION_KEYWORDS:
        if keyword.lower() in query_lower:
            matched_patterns.append(keyword)
    
    if matched_patterns:
        return True, matched_patterns
    
    return False, []

def detect_anomalous_characters(query: str) -> Tuple[bool, List[str]]:
    """
    检测异常字符模式
    
    :param query: 用户输入的问题
    :return: (是否检测到异常, 异常类型列表)
    """
    anomalies = []
    
    if len(query) > 500:
        anomalies.append("文本过长")
    
    if len(query) < 1:
        anomalies.append("空输入")
    
    url_pattern = r'https?://[^\s]+'
    if re.search(url_pattern, query):
        anomalies.append("包含URL")
    
    base64_pattern = r'(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?'
    base64_matches = re.findall(base64_pattern, query)
    for match in base64_matches:
        if len(match) > 20:
            anomalies.append("包含Base64编码")
            break
    
    if re.search(r'[<>{}[\]|`~!@#$%^&*()+=;:\'"\\]+{3,}', query):
        anomalies.append("异常符号重复")
    
    return len(anomalies) > 0, anomalies

def is_safe_query(query: str) -> Tuple[bool, str]:
    """
    综合检测用户输入是否安全
    
    :param query: 用户输入的问题
    :return: (是否安全, 错误信息/提示)
    """
    is_injection, injection_patterns = detect_prompt_injection(query)
    if is_injection:
        return False, f"检测到提示词注入攻击，匹配模式: {', '.join(injection_patterns)}"
    
    has_anomaly, anomalies = detect_anomalous_characters(query)
    if has_anomaly:
        return False, f"输入包含异常内容: {', '.join(anomalies)}"
    
    return True, ""