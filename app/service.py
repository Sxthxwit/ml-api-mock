"""ตัวอย่าง Application API ที่แสดง graceful degradation ให้ UI ใช้งาน."""
import asyncio
import os
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import Literal

from app.common import fallback_hierarchy
from app.strategies import Breaker, execute
from app.ui import DEMO_HTML


class TicketRequest(BaseModel):
    text: str = Field(min_length=1)


class TicketResponse(BaseModel):
    label: str
    source: str
    fallback_tier: str | None
    mode: str
    user_message: str


class DemoScenarioRequest(BaseModel):
    scenario: Literal[
        "normal", "outage", "latency", "rate_limit",
        "malformed", "empty", "irrelevant", "drift",
    ]


breaker = Breaker()
bulkhead = asyncio.Semaphore(20)


@asynccontextmanager
async def lifespan(app):
    app.state.client = httpx.AsyncClient(
        base_url=os.getenv("ML_API_URL", "http://127.0.0.1:8000"),
        timeout=5,
        trust_env=False,
    )
    yield
    await app.state.client.aclose()


app = FastAPI(title="Degradation-aware Ticket Service", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def demo_page():
    """หน้า UI สำหรับพรีเซนต์ normal/degraded/human-review states."""
    return HTMLResponse(DEMO_HTML)


@app.put("/demo/scenario")
async def configure_demo(value: DemoScenarioRequest):
    """ตั้ง Mock API ให้ fault เกิดทันที ใช้เฉพาะห้องทดลอง/การสาธิต."""
    global breaker
    response = await app.state.client.put("/config", json={
        "scenario": value.scenario,
        "seed": 42,
        "start_delay": 0,
        "fault_start": 0,
        "fault_duration": 600,
        "latency": 0.02,
        "spike_latency": 0.8,
        "soft_failure_rate": 1,
    })
    response.raise_for_status()
    breaker = Breaker()
    return {"scenario": value.scenario, "breaker_state": breaker.state}


@app.post("/tickets/classify", response_model=TicketResponse)
async def classify_ticket(ticket: TicketRequest):
    request_id = str(uuid.uuid4())
    acquired = False
    try:
        async with asyncio.timeout(0.05):
            await bulkhead.acquire()
            acquired = True
    except TimeoutError:
        label, tier = fallback_hierarchy(ticket.text)
        return TicketResponse(
            label=label, source="fallback", fallback_tier=tier,
            mode="degraded",
            user_message="ระบบมีคำขอจำนวนมาก จึงใช้โหมดสำรอง ผลลัพธ์อาจมีข้อจำกัด",
        )

    try:
        result = await execute(
            app.state.client, "D", breaker, request_id,
            ticket.text, seed=42, timeout=0.3,
        )
    finally:
        if acquired:
            bulkhead.release()

    if result["label"] == "human_review":
        mode = "human_review"
        message = "ระบบอัตโนมัติยังไม่มั่นใจ คำขอนี้ถูกส่งต่อให้เจ้าหน้าที่ตรวจสอบ"
    elif result["source"] == "fallback":
        mode = "degraded"
        message = "ขณะนี้ระบบกำลังใช้โหมดสำรอง ผลลัพธ์อาจมีข้อจำกัด"
    else:
        mode = "normal"
        message = "จัดหมวดหมู่สำเร็จ"

    return TicketResponse(
        label=result["label"], source=result["source"],
        fallback_tier=result["fallback_tier"], mode=mode,
        user_message=message,
    )


@app.get("/health")
async def health():
    return {"status": "ok", "breaker_state": breaker.state,
            "failure_rate": breaker.failure_rate}
