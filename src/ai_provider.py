# -*- coding: utf-8 -*-
"""可扩展 AI 提供方适配层。

当前支持：
1. 本地 Ollama（无需 API Key）
2. 自定义 Chat Completions 兼容接口（适用于提供兼容协议的云端模型）
"""
import json
from urllib import error as urlerror
from urllib import request as urlrequest


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "hypotheses": {"type": "array", "items": {"type": "string"}},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "expected_impact": {"type": "string"},
                    "verify_metric": {"type": "string"},
                    "review_time": {"type": "string"},
                },
                "required": ["action", "expected_impact", "verify_metric", "review_time"],
            },
        },
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "hypotheses", "actions", "risks"],
}


def list_ollama_models(base_url="http://localhost:11434", timeout=2):
    """返回本地 Ollama 已安装模型名称。"""
    try:
        req = urlrequest.Request(f"{base_url.rstrip('/')}/api/tags", method="GET")
        with urlrequest.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = [item.get("name") or item.get("model") for item in payload.get("models", [])]
        return [name for name in models if name], ""
    except (urlerror.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return [], str(exc)


def _build_prompt(context):
    return f"""你是亚马逊运营分析助手。请只依据给定数据生成中文经营复盘草稿。
要求：
1. 明确区分已知事实与待验证假设，不得编造竞品变化、关键词表现或经营结果；
2. 最多给出 3 个动作，按优先级排列；
3. 每个动作包含预期影响、验证指标和复盘时间；
4. 指出利润、库存和合规风险；
5. 只返回 JSON，不要使用 Markdown；字段必须为 summary、hypotheses、actions、risks。

SKU 数据：
{json.dumps(context, ensure_ascii=False, default=str)}"""


def _request_json(url, payload, headers=None, timeout=120):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    req = urlrequest.Request(url, data=body, headers=request_headers, method="POST")
    try:
        with urlrequest.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AI 接口返回 {exc.code}：{detail[:500]}") from exc
    except (urlerror.URLError, TimeoutError) as exc:
        raise RuntimeError("无法连接 AI 接口，请检查地址、网络或本地服务状态。") from exc


def _parse_result(content):
    text = (content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("模型没有返回有效 JSON，请换一个模型或重试。") from exc
    missing = [key for key in REVIEW_SCHEMA["required"] if key not in result]
    if missing:
        raise RuntimeError(f"AI 结果缺少字段：{', '.join(missing)}")
    return result


def generate_review(provider, context, *, model, base_url="", api_key=""):
    """按提供方生成经营复盘；新增提供方时只需在这里增加适配分支。"""
    prompt = _build_prompt(context)
    if provider == "ollama":
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": REVIEW_SCHEMA,
            "options": {"temperature": 0.2},
        }
        response = _request_json(f"{base_url.rstrip('/')}/api/chat", payload)
        return _parse_result(response.get("message", {}).get("content", ""))

    if provider == "compatible":
        if not api_key:
            raise RuntimeError("请填写 API Key。")
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
        response = _request_json(
            base_url.rstrip("/"),
            payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("接口返回结构不兼容，请确认它支持 Chat Completions 格式。") from exc
        return _parse_result(content)

    raise RuntimeError(f"不支持的 AI 提供方：{provider}")
