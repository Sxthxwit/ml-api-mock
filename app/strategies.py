import asyncio
import time
from typing import Literal
import httpx
from pydantic import BaseModel, ValidationError
from app.common import draw, fallback

class Output(BaseModel):
    label: Literal['billing', 'account', 'technical']

class Breaker:
    """ตัวตัดวงจร: closed → open → half_open → closed/open."""
    def __init__(self, threshold=3, cooldown=1):
        self.threshold, self.cooldown = threshold, cooldown
        self.failures = 0
        self.state = 'closed'
        self.until = 0
        self.generation = 0
        self.open_since = None
        self.open_seconds = 0

    def permit(self):
        now = time.monotonic()
        if self.state == 'open':
            if now < self.until:
                return None
            self.open_seconds += now - self.open_since
            self.open_since = None
            self.state = 'half_open'
            return self.generation  # Exactly one probe; other calls are rejected.
        if self.state == 'half_open':
            return None
        return self.generation

    def record(self, token, success):
        if token != self.generation:
            return  # Ignore stale in-flight results from a previous state.
        if success:
            self.failures = 0
            if self.state == 'half_open':
                self.state = 'closed'
                self.generation += 1
        else:
            self.failures += 1
            if self.state == 'half_open' or self.failures >= self.threshold:
                self.state = 'open'
                self.generation += 1
                self.open_since = time.monotonic()
                self.until = self.open_since + self.cooldown

    def duration(self):
        return self.open_seconds + (time.monotonic() - self.open_since if self.open_since is not None else 0)

async def call_primary(client, request_id, text, timeout, attempt=0):
    """เรียก API หนึ่งครั้ง แล้วคืนทั้งคำตอบและข้อมูลสำหรับวัดผล."""
    started = time.monotonic()
    label, status = None, None
    retryable = False
    error = ''
    try:
        # deadline ครอบคลุมทั้ง attempt ไม่ใช่แค่ช่วงรอข้อมูลของ HTTPX
        async with asyncio.timeout(timeout):
            response = await client.post('/classify', json={
                'request_id': request_id, 'attempt': attempt, 'text': text,
            })
            status = response.status_code
            response.raise_for_status()
            label = Output.model_validate(response.json()).label
    except httpx.HTTPStatusError:
        retryable = status in (500, 502, 503, 504)
        error = f'http_{status}'
    except (TimeoutError, httpx.TimeoutException, httpx.NetworkError):
        retryable = True
        error = 'timeout_or_connection'
    except (httpx.RequestError, ValueError, ValidationError):
        error = 'invalid_output_or_request'  # ไม่ retry โดยไม่มีเหตุผล
    return {
        'label': label, 'retryable': retryable,
        'log': {'attempt': attempt, 'started': started, 'finished': time.monotonic(),
                'status': status, 'transport_success': status == 200,
                'valid_output': label is not None, 'error': error},
    }


def result_from(call):
    return {'label': call['label'],
            'source': 'primary' if call['label'] is not None else 'none',
            'rejected': False, 'attempts': [call['log']]}


async def no_protection(client, request_id, text, timeout):
    """A: เรียกหนึ่งครั้ง มี timeout เพื่อไม่ให้รอไม่สิ้นสุด."""
    call = await call_primary(client, request_id, text, timeout)
    return result_from(call)


async def retry_only(client, request_id, text, timeout, seed):
    """B: เรียกรวมไม่เกิน 3 ครั้ง รอแบบ exponential backoff + jitter."""
    logs = []
    for attempt in range(3):
        call = await call_primary(client, request_id, text, timeout, attempt)
        logs.append(call['log'])
        if call['label'] is not None or not call['retryable'] or attempt == 2:
            break
        delay = 0.05 * (2 ** attempt) * draw(seed, request_id, attempt, 'jitter')
        await asyncio.sleep(delay)
    result = result_from(call)
    result['attempts'] = logs
    return result


async def circuit_breaker(client, request_id, text, timeout, breaker):
    """C: ถ้าวงจรเปิดอยู่ ให้หยุดทันที; ไม่ retry."""
    token = breaker.permit()
    if token is None:
        return {'label': None, 'source': 'none', 'rejected': True, 'attempts': []}
    call = await call_primary(client, request_id, text, timeout)
    breaker.record(token, call['label'] is not None)
    return result_from(call)


async def circuit_breaker_with_fallback(client, request_id, text, timeout, breaker):
    """D: ทำเหมือน C และใช้กฎสำรองเมื่อไม่ได้คำตอบจาก Primary."""
    result = await circuit_breaker(client, request_id, text, timeout, breaker)
    if result['source'] == 'none':
        result['label'] = fallback(text)
        result['source'] = 'fallback'
    return result


async def execute(client, strategy, breaker, request_id, text, seed, timeout):
    started = time.monotonic()
    if strategy == 'A':
        result = await no_protection(client, request_id, text, timeout)
    elif strategy == 'B':
        result = await retry_only(client, request_id, text, timeout, seed)
    elif strategy == 'C':
        result = await circuit_breaker(client, request_id, text, timeout, breaker)
    elif strategy == 'D':
        result = await circuit_breaker_with_fallback(client, request_id, text, timeout, breaker)
    else:
        raise ValueError('strategy must be A, B, C or D')
    result['latency'] = time.monotonic() - started
    return result
