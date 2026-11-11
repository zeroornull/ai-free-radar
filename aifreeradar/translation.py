"""Additive Simplified-Chinese machine translation of English lead/message text.

Originals stay authoritative: only *_zh fields are ever populated, and a
translation failure leaves them empty instead of failing the collection task.
The single configured model is reused (same routing as research); the cache is
content-addressed by (sha256(original), "zh") so unchanged text is never
re-translated, while a changed original always misses and is translated anew.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openai_compatible import OpenAICompatibleProvider

from .config import ConfigurationError, Settings
from .models import UNKNOWN, CollectedMessage, Resource

# Translation scope per the shared contract: message text plus the nested
# policy's descriptive fields, and Resource.failure_reason. Provider/service
# names, Resource.policy descriptive fields, and evidence are never translated.
MESSAGE_TRANSLATED_FIELDS = ("title", "summary", "end_reason")
POLICY_TRANSLATED_FIELDS = (
    "quota",
    "quota_unit",
    "refresh_cycle",
    "rate_limit",
    "claim_conditions",
    "expiry_notes",
    "region_restrictions",
)

_CJK = re.compile(r"[\u4e00-\u9fff]")
_ASCII_LETTERS = re.compile(r"[A-Za-z]")
_MAX_BATCH = 20

INSTRUCTIONS = (
    "You translate free-AI-API lead and message text into faithful Simplified Chinese. "
    "Translate every value of the supplied JSON object and return exactly the same keys. "
    "Keep brand names, provider and service names, URLs, code, model identifiers and "
    "numbers verbatim. Do not add commentary, explanations or markdown fences. "
    "Never translate evidence quotations; only the supplied descriptive values are in "
    "scope. Return a value unchanged when it is already Chinese."
)


def needs_translation(text: str) -> bool:
    """English descriptive text needs zh; Chinese, placeholders and symbols do not."""
    value = text.strip()
    if not value or value == UNKNOWN:
        return False
    cjk = len(_CJK.findall(value))
    letters = len(_ASCII_LETTERS.findall(value))
    if not letters:
        # Pure digits/punctuation, or text that is already Chinese.
        return False
    return cjk / letters < 0.3


class Translator(Protocol):
    async def translate(self, texts: dict[str, str]) -> dict[str, str]: ...


class TranslationBatch(BaseModel):
    translations: dict[str, str] = Field(default_factory=dict)


class ModelTranslator:
    """Translate with the single configured model; never raises to its caller."""

    def __init__(self, settings: Settings, *, model: Model | None = None) -> None:
        self._settings = settings
        self._injected_model = model
        self._agent: Agent[object, TranslationBatch] | None = None
        self._cache_path = Path(settings.data_dir) / "translation_cache.json"
        self._cache: dict[tuple[str, str], str] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        try:
            raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(key, str) and key.endswith(":zh") and isinstance(value, str) and value:
                    self._cache[(key[:-3], "zh")] = value

    def _save_cache(self) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {f"{digest}:{lang}": value for (digest, lang), value in self._cache.items()}
            self._cache_path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    def _model(self) -> Model:
        # Same routing as HarnessResearcher._model; kept local so the research
        # contract and its verbatim evidence validation stay untouched.
        if self._injected_model is not None:
            return self._injected_model
        key = self._settings.model_credential()
        provider, name = self._settings.model_route()
        base_url = self._settings.model_base_url
        if provider == "anthropic":
            return AnthropicModel(
                name,
                provider=AnthropicProvider(
                    api_key=key, base_url=base_url or "https://api.anthropic.com"
                ),
            )
        if provider == "deepseek":
            client = AsyncOpenAI(api_key=key, base_url=base_url or "https://api.deepseek.com")
            return OpenAIChatModel(name, provider=DeepSeekProvider(openai_client=client))
        if provider == "compatible":
            if not base_url:
                raise ConfigurationError(
                    "model_base_url is required for a compatible endpoint; no default endpoint is assumed"
                )
            service = urlsplit(base_url).hostname or "compatible"
            return OpenAIChatModel(
                name,
                provider=OpenAICompatibleProvider(service, base_url=base_url, api_key=key),
            )
        openai = OpenAIProvider(api_key=key, base_url=base_url or "https://api.openai.com/v1")
        if provider == "openai-responses":
            return OpenAIResponsesModel(name, provider=openai)
        return OpenAIChatModel(name, provider=openai)

    def _get_agent(self) -> Agent[object, TranslationBatch]:
        if self._agent is None:
            self._agent = Agent(
                self._model(),
                name="free-api-zh-translator",
                output_type=TranslationBatch,
                instructions=INSTRUCTIONS,
            )
        return self._agent

    @staticmethod
    def _cache_key(text: str) -> tuple[str, str]:
        return (hashlib.sha256(text.encode("utf-8")).hexdigest(), "zh")

    async def translate(self, texts: dict[str, str]) -> dict[str, str]:
        """Return zh for the keys that need it; failed keys are simply absent."""
        result: dict[str, str] = {}
        pending: dict[str, str] = {}
        for key, text in texts.items():
            if not needs_translation(text):
                continue
            cached = self._cache.get(self._cache_key(text))
            if cached is not None:
                result[key] = cached
            else:
                pending[key] = text
        if not pending:
            return result
        items = list(pending.items())
        changed = False
        for start in range(0, len(items), _MAX_BATCH):
            chunk = dict(items[start : start + _MAX_BATCH])
            try:
                prompt = (
                    "Translate the values of this JSON object into Simplified Chinese, "
                    "keeping every key unchanged:\n" + json.dumps(chunk, ensure_ascii=False)
                )
                answer = await self._get_agent().run(prompt)
                translations = answer.output.translations
            except Exception:  # noqa: BLE001,S112 — translation must never fail its caller
                continue
            for key, text in chunk.items():
                value = translations.get(key)
                if isinstance(value, str) and value.strip() and _CJK.search(value):
                    value = value.strip()
                    self._cache[self._cache_key(text)] = value
                    result[key] = value
                    changed = True
        if changed:
            self._save_cache()
        return result


async def translate_message[MessageT: CollectedMessage](
    translator: Translator, message: MessageT
) -> MessageT:
    """Copy a message with *_zh populated; the original object is never mutated."""
    texts: dict[str, str] = {}
    for field in MESSAGE_TRANSLATED_FIELDS:
        value = getattr(message, field)
        if needs_translation(value):
            texts[field] = value
    for field in POLICY_TRANSLATED_FIELDS:
        value = getattr(message.policy, field)
        if needs_translation(value):
            texts[f"policy.{field}"] = value
    if not texts:
        return message
    translated = await translator.translate(texts)
    updates: dict[str, object] = {}
    for field in MESSAGE_TRANSLATED_FIELDS:
        if field in translated:
            updates[f"{field}_zh"] = translated[field]
    policy_updates = {
        f"{field}_zh": translated[f"policy.{field}"]
        for field in POLICY_TRANSLATED_FIELDS
        if f"policy.{field}" in translated
    }
    if policy_updates:
        updates["policy"] = message.policy.model_copy(update=policy_updates)
    if not updates:
        return message
    return message.model_copy(deep=True, update=updates)


async def translate_resource_failure(translator: Translator, resource: Resource) -> Resource:
    """Copy a resource with failure_reason_zh populated; everything else stays."""
    reason = resource.failure_reason
    if not needs_translation(reason):
        return resource
    translated = await translator.translate({"failure_reason": reason})
    value = translated.get("failure_reason")
    if not value:
        return resource
    return resource.model_copy(deep=True, update={"failure_reason_zh": value})