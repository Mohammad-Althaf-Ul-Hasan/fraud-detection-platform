"""Provider-agnostic LLM client for streaming case narratives.

Provider is auto-detected from env vars, in this priority order:
  1. LLM_PROVIDER (explicit: anthropic | openai | ollama | deferred)
  2. ANTHROPIC_API_KEY present → anthropic
  3. OPENAI_API_KEY present → openai
  4. Ollama reachable at OLLAMA_BASE_URL → ollama
  5. Otherwise → deferred (returns setup instructions, no API call)

All imports are lazy (inside provider functions) so missing packages
don't break the app — install anthropic OR openai per your preference.
"""
import json
import logging
import os
from typing import AsyncIterator

log = logging.getLogger("llm")

PROVIDER      = os.getenv("LLM_PROVIDER", "").lower().strip()
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
OPENAI_KEY    = os.getenv("OPENAI_API_KEY", "").strip()
OLLAMA_URL    = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

SYSTEM_PROMPT = (
    "You are a fraud analyst explaining decisions to compliance reviewers. "
    "Be concise, factual, and never speculate beyond the data given. "
    "Write in plain prose, 3-4 sentences, no headers, no greetings."
)


def detect_provider() -> str:
    if PROVIDER in ("anthropic", "openai", "ollama", "deferred"):
        return PROVIDER
    if ANTHROPIC_KEY:
        return "anthropic"
    if OPENAI_KEY:
        return "openai"
    try:
        import httpx
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=1.5)
        if r.status_code == 200:
            return "ollama"
    except Exception:
        pass
    return "deferred"


async def stream_narrative(prompt: str) -> AsyncIterator[str]:
    provider = detect_provider()
    log.info(f"LLM narrative provider: {provider}")
    if provider == "anthropic":
        async for chunk in _stream_anthropic(prompt):
            yield chunk
    elif provider == "openai":
        async for chunk in _stream_openai(prompt):
            yield chunk
    elif provider == "ollama":
        async for chunk in _stream_ollama(prompt):
            yield chunk
    else:
        yield _deferred_text()


async def _stream_anthropic(prompt: str) -> AsyncIterator[str]:
    from anthropic import AsyncAnthropic
    client = AsyncAnthropic(api_key=ANTHROPIC_KEY)
    async with client.messages.stream(
        model="claude-3-5-haiku-latest",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def _stream_openai(prompt: str) -> AsyncIterator[str]:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_KEY)
    stream = await client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=400,
        stream=True,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def _stream_ollama(prompt: str) -> AsyncIterator[str]:
    import httpx
    async with httpx.AsyncClient(timeout=90.0) as client:
        async with client.stream(
            "POST",
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": f"{SYSTEM_PROMPT}\n\n{prompt}",
                "stream": True,
            },
        ) as r:
            async for line in r.aiter_lines():
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if "response" in obj and obj["response"]:
                    yield obj["response"]
                if obj.get("done"):
                    break


def _deferred_text() -> str:
    return (
        "Narrative generation is not configured yet.\n\n"
        "To enable plain-English case narratives, set one of these in .env "
        "at the project root, then rebuild the backend image:\n\n"
        "  ANTHROPIC_API_KEY=sk-ant-...    (Claude Haiku 3.5, ~$0.001/narrative)\n"
        "  OPENAI_API_KEY=sk-...           (GPT-4o-mini, ~$0.001/narrative)\n"
        "  OLLAMA_BASE_URL=http://host.docker.internal:11434    (local, free)\n\n"
        "Alternatively set LLM_PROVIDER=anthropic|openai|ollama explicitly."
    )