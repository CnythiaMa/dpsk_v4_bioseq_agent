"""Thin OpenAI-compatible chat wrapper (Volcengine Ark) with an optional adaptive
concurrency limiter + retry/backoff on 429/5xx."""
import random
import time

import httpx

from . import config

MAX_RETRY = 8


def _request(client, payload, limiter=None):
    """POST with concurrency gating (limiter) and retry/backoff on 429/5xx. Returns the
    response ``message`` dict. A concurrency slot is held only while a request is in
    flight, never during backoff sleeps."""
    url = f"{config.BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {config.API_KEY}", "Content-Type": "application/json"}
    if config.THINKING and "thinking" not in payload:
        payload["thinking"] = {"type": config.THINKING}
    attempt = 0
    while True:
        if limiter:
            limiter.acquire()
        try:
            r = client.post(url, json=payload, headers=headers, timeout=config.HTTP_TIMEOUT)
        except (httpx.TransportError, httpx.TimeoutException):
            if limiter:
                limiter.on_throttle()
            attempt += 1
            if attempt > MAX_RETRY:
                raise
            time.sleep(min(30, 2 ** attempt * 0.5 + random.random()))
            continue
        finally:
            if limiter:
                limiter.release()

        if r.status_code == 429 or r.status_code >= 500:
            if limiter:
                limiter.on_throttle()
            attempt += 1
            if attempt > MAX_RETRY:
                r.raise_for_status()
            retry_after = r.headers.get("retry-after")
            wait = (float(retry_after) if (retry_after and retry_after.replace(".", "", 1).isdigit())
                    else min(30, 2 ** attempt * 0.5 + random.random()))
            time.sleep(wait)
            continue

        r.raise_for_status()
        if limiter:
            limiter.on_success()
        return r.json()["choices"][0]["message"]


def chat(messages, tools=None, tool_choice=None, max_tokens=None, client=None, limiter=None):
    payload = {"model": config.MODEL, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice
    if max_tokens:
        payload["max_tokens"] = max_tokens
    own = client is None
    if own:
        client = httpx.Client(timeout=config.HTTP_TIMEOUT)
    try:
        return _request(client, payload, limiter=limiter)
    finally:
        if own:
            client.close()


def text(messages, max_tokens=None, client=None, limiter=None):
    """Convenience: return assistant text (falls back to reasoning_content if empty)."""
    msg = chat(messages, max_tokens=max_tokens, client=client, limiter=limiter)
    return (msg.get("content") or "").strip() or (msg.get("reasoning_content") or "").strip()
