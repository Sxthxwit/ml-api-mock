import asyncio
import time
from collections import deque
from typing import Literal
import httpx
from pydantic import BaseModel, ValidationError
from app.common import draw, fallback_hierarchy


class Output(BaseModel):
    label: Literal["billing", "account", "technical"]


class Breaker:
    """Sliding-window, quality-aware circuit breaker."""

    def __init__(self, window_size=10, minimum_calls=5,
                 failure_rate_threshold=0.5, cooldown=1):
        self.window_size = window_size
        self.minimum_calls = minimum_calls
        self.failure_rate_threshold = failure_rate_threshold
        self.cooldown = cooldown
        self.outcomes = deque(maxlen=window_size)
        self.state = "closed"
        self.until = 0
        self.generation = 0
        self.open_since = None
        self.open_seconds = 0

    @property
    def failure_rate(self):
        return sum(not success for success in self.outcomes) / len(self.outcomes) if self.outcomes else 0

    def permit(self):
        now = time.monotonic()
        if self.state == "open":
            if now < self.until:
                return None
            self.open_seconds += now - self.open_since
            self.open_since = None
            self.state = "half_open"
            return self.generation
        if self.state == "half_open":
            return None
        return self.generation

    def _open(self):
        self.state = "open"
        self.generation += 1
        self.open_since = time.monotonic()
        self.until = self.open_since + self.cooldown

    def record(self, token, success):
        if token != self.generation:
            return
        if self.state == "half_open":
            if success:
                self.state = "closed"
                self.generation += 1
                self.outcomes.clear()
            else:
                self._open()
            return

        self.outcomes.append(success)
        if len(self.outcomes) >= self.minimum_calls and self.failure_rate >= self.failure_rate_threshold:
            self._open()

    def duration(self):
        active = time.monotonic() - self.open_since if self.open_since is not None else 0
        return self.open_seconds + active


async def call_primary(client, request_id, text, timeout, attempt=0):
    started = time.monotonic()
    label, status, retry_after = None, None, 0.0
    retryable = False
    error = ""
    try:
        async with asyncio.timeout(timeout):
            response = await client.post("/classify", json={
                "request_id": request_id, "attempt": attempt, "text": text,
            })
            status = response.status_code
            response.raise_for_status()
            label = Output.model_validate(response.json()).label
    except httpx.HTTPStatusError as exc:
        retryable = status in (429, 500, 502, 503, 504)
        if status == 429:
            try:
                retry_after = float(exc.response.headers.get("Retry-After", 0))
            except ValueError:
                retry_after = 0
        error = f"http_{status}"
    except (TimeoutError, httpx.TimeoutException, httpx.NetworkError):
        retryable = True
        error = "timeout_or_connection"
    except (httpx.RequestError, ValueError, ValidationError):
        error = "invalid_output_or_request"

    return {
        "label": label,
        "retryable": retryable,
        "retry_after": retry_after,
        "log": {
            "attempt": attempt, "started": started, "finished": time.monotonic(),
            "status": status, "transport_success": status == 200,
            "valid_output": label is not None, "error": error,
        },
    }


def result_from(call):
    return {
        "label": call["label"],
        "source": "primary" if call["label"] is not None else "none",
        "fallback_tier": None,
        "rejected": False,
        "attempts": [call["log"]],
    }


async def no_protection(client, request_id, text, timeout):
    return result_from(await call_primary(client, request_id, text, timeout))


async def retry_only(client, request_id, text, timeout, seed):
    logs = []
    for attempt in range(3):
        call = await call_primary(client, request_id, text, timeout, attempt)
        logs.append(call["log"])
        if call["label"] is not None or not call["retryable"] or attempt == 2:
            break
        jittered_backoff = 0.05 * (2 ** attempt) * draw(seed, request_id, attempt, "jitter")
        await asyncio.sleep(max(jittered_backoff, call["retry_after"]))
    result = result_from(call)
    result["attempts"] = logs
    return result


async def circuit_breaker(client, request_id, text, timeout, breaker):
    token = breaker.permit()
    if token is None:
        return {"label": None, "source": "none", "fallback_tier": None,
                "rejected": True, "attempts": []}
    call = await call_primary(client, request_id, text, timeout)
    # HTTP 200 ที่ schema/business validation ไม่ผ่าน นับเป็น failure ด้วย
    breaker.record(token, call["label"] is not None)
    return result_from(call)


async def circuit_breaker_with_fallback(client, request_id, text, timeout, breaker):
    result = await circuit_breaker(client, request_id, text, timeout, breaker)
    if result["source"] == "none":
        result["label"], result["fallback_tier"] = fallback_hierarchy(text)
        result["source"] = "fallback"
    return result


async def execute(client, strategy, breaker, request_id, text, seed, timeout):
    started = time.monotonic()
    if strategy == "A":
        result = await no_protection(client, request_id, text, timeout)
    elif strategy == "B":
        result = await retry_only(client, request_id, text, timeout, seed)
    elif strategy == "C":
        result = await circuit_breaker(client, request_id, text, timeout, breaker)
    elif strategy == "D":
        result = await circuit_breaker_with_fallback(client, request_id, text, timeout, breaker)
    else:
        raise ValueError("strategy must be A, B, C or D")
    result["latency"] = time.monotonic() - started
    return result
