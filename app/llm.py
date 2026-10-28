"""One wrapper for every model call: Gemini + Nemotron + offline fallback.

Agents call only `ask()`. It routes each task to the right provider, retries on
the other provider if one fails, and - if no key works - runs the agent's own
offline rule (`fallback`) so the product never stops working in a live demo.

Returns (result, model_used) so the audit log can show who decided what.
"""
import base64
import logging
import re
from typing import Any, Callable, Optional

from app import config

log = logging.getLogger("paymitra.llm")

_gemini_client = None
_nvidia_client = None


def _gemini():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options={"timeout": int(config.LLM_TIMEOUT_SECONDS * 1000)},
        )
    return _gemini_client


def _nvidia():
    global _nvidia_client
    if _nvidia_client is None:
        from openai import OpenAI
        _nvidia_client = OpenAI(base_url=config.NVIDIA_BASE_URL, api_key=config.NVIDIA_API_KEY,
                                timeout=config.LLM_TIMEOUT_SECONDS, max_retries=1)
    return _nvidia_client


# task -> ordered list of (provider, model). First that works wins.
def _routes(task: str) -> list[tuple[str, str]]:
    table = {
        "reason":   [("gemini", config.MODEL_REASON), ("nvidia", config.MODEL_CLASSIFY)],
        "cheap":    [("gemini", config.MODEL_CHEAP), ("nvidia", config.MODEL_CLASSIFY)],
        "classify": [("nvidia", config.MODEL_CLASSIFY), ("gemini", config.MODEL_CHEAP)],
    }
    return table[task]


def _available(provider: str) -> bool:
    return bool(config.GEMINI_API_KEY) if provider == "gemini" else bool(config.NVIDIA_API_KEY)


def _call_gemini(model: str, prompt: str, schema) -> str:
    extra = {}
    if schema is not None:
        extra["response_format"] = {"type": "text", "mime_type": "application/json",
                                    "schema": schema.model_json_schema()}
    interaction = _gemini().interactions.create(model=model, input=prompt, **extra)
    return interaction.output_text


def _call_nvidia(model: str, prompt: str, schema) -> str:
    if schema is not None:
        prompt += ("\n\nReply with one JSON object only, no prose, matching this JSON schema:\n"
                   f"{schema.model_json_schema()}")
    resp = _nvidia().chat.completions.create(
        model=model, temperature=0.1, max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or ""


def _clean(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = text.replace("```json", "").replace("```", "").strip()
    # keep only the outermost JSON object if the model added chatter around it
    if "{" in text and "}" in text and not text.startswith("{"):
        text = text[text.find("{"): text.rfind("}") + 1]
    return text


def ask(task: str, prompt: str, schema=None,
        fallback: Optional[Callable[[], Any]] = None) -> tuple[Any, str]:
    if config.llm_online():
        for provider, model in _routes(task):
            if not _available(provider):
                continue
            try:
                raw = (_call_gemini if provider == "gemini" else _call_nvidia)(model, prompt, schema)
                text = _clean(raw) if schema is not None else (raw or "").strip()
                result = schema.model_validate_json(text) if schema is not None else text
                if result in ("", None):
                    raise ValueError("empty response")
                return result, model
            except Exception as exc:  # network, quota, bad JSON ... try the next one
                log.warning("LLM %s/%s failed for task %s: %s", provider, model, task, exc)
    if fallback is None:
        raise RuntimeError("No LLM available and no offline fallback given")
    return fallback(), "offline-rules"


def describe_image(image_bytes: bytes, question: str, mime: str = "image/jpeg") -> tuple[str, str]:
    """Read a POD photo / portal screenshot with Nemotron VL. Offline: returns ''."""
    if not (config.llm_online() and config.NVIDIA_API_KEY):
        return "", "offline-rules"
    b64 = base64.b64encode(image_bytes).decode()
    try:
        resp = _nvidia().chat.completions.create(
            model=config.MODEL_VISION, temperature=0.1, max_tokens=600,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]}],
        )
        return _clean(resp.choices[0].message.content or ""), config.MODEL_VISION
    except Exception as exc:
        log.warning("Vision call failed: %s", exc)
        return "", "offline-rules"


_NUM = re.compile(r"\d[\d,\.]*")


def numbers_preserved(source: str, rewritten: str) -> bool:
    """Guardrail: an LLM rewrite must not add, drop or change any number."""
    norm = lambda s: sorted(n.replace(",", "").rstrip(".") for n in _NUM.findall(s))
    return norm(source) == norm(rewritten)


def polish(text: str, instruction: str) -> tuple[str, str]:
    """Let the cheap model improve wording, but only if every number survives."""
    if not config.llm_online():
        return text, "template"
    prompt = (f"{instruction}\nKeep every number, amount, date and invoice number exactly as written. "
              f"Return only the rewritten message.\n\nMESSAGE:\n{text}")
    out, model = ask("cheap", prompt, fallback=lambda: text)
    if model != "offline-rules" and isinstance(out, str) and numbers_preserved(text, out):
        return out.strip(), model
    return text, "template"
