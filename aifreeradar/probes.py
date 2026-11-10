"""Credential probes backing POST /api/settings/test; never echo secrets."""

from __future__ import annotations

import httpx

from .config import ConfigurationError, Settings
from .research import ResearchError, SearchClient


class SettingsProbeError(RuntimeError):
    """The probed service could not be reached or authenticated."""


async def probe_model(settings: Settings) -> str:
    provider, name = settings.model_route()
    key = settings.model_credential()  # raises ConfigurationError when missing
    if provider == "anthropic":
        base = (settings.model_base_url or "https://api.anthropic.com").rstrip("/")
        url = f"{base}/v1/models"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    elif provider in {"openai", "openai-chat", "openai-responses"}:
        base = (settings.model_base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base}/models"
        headers = {"Authorization": f"Bearer {key}"}
    elif provider == "deepseek":
        base = (settings.model_base_url or "https://api.deepseek.com/v1").rstrip("/")
        url = f"{base}/models"
        headers = {"Authorization": f"Bearer {key}"}
    else:  # compatible
        if not settings.model_base_url:
            raise ConfigurationError("compatible 模型需要配置 model_base_url")
        url = f"{settings.model_base_url.rstrip('/')}/models"
        headers = {"Authorization": f"Bearer {key}"}
    try:
        async with (
            httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client
        ):
            response = await client.get(url, headers=headers)
    except httpx.HTTPError:
        raise SettingsProbeError("无法连接模型端点，请检查地址或网络。") from None
    if response.status_code != 200:
        raise SettingsProbeError(f"模型端点返回 HTTP {response.status_code}")
    return f"模型服务可用（{provider}:{name}）。"


async def probe_search(settings: Settings) -> str:
    client = SearchClient(settings)  # raises ConfigurationError when credential missing
    try:
        results = await client.search("AIFreeRadar")
    except (ResearchError, httpx.HTTPError) as exc:
        raise SettingsProbeError("搜索服务探测失败，请检查凭据或网络。") from exc
    if not results:
        raise SettingsProbeError("搜索服务已连接，但未返回任何结果。")
    return f"搜索服务可用，返回 {len(results)} 条结果。"