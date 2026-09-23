import asyncio
import time
from typing import Literal
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from app.common import LABELS, TICKETS, draw

Scenario = Literal[
    "normal", "outage", "latency", "error10", "error30", "error50",
    "rate_limit", "malformed", "empty", "irrelevant", "drift",
]
app = FastAPI(title="Resilience Lab Mock ML API")

class Config(BaseModel):
    scenario: Scenario = "normal"
    seed: int = 42
    start_delay: float = Field(default=0.2, ge=0)
    fault_start: float = Field(default=3, ge=0)
    fault_duration: float = Field(default=4, gt=0)
    latency: float = Field(default=0.02, ge=0)
    spike_latency: float = Field(default=0.8, ge=0)
    soft_failure_rate: float = Field(default=0.3, ge=0, le=1)

class Ticket(BaseModel):
    request_id: str
    attempt: int = Field(default=0, ge=0)
    text: str

# เก็บสถานการณ์ เวลาเริ่ม และเหตุการณ์ของรอบปัจจุบัน
config = Config()
epoch = time.monotonic()
events = []

@app.put("/config")
async def configure(value: Config):
    global config, epoch
    config = value
    epoch = time.monotonic() + value.start_delay
    events.clear()
    return {"config": value.model_dump(), "epoch": epoch}

@app.get("/events")
async def get_events():
    return events

@app.post("/classify")
async def classify(ticket: Ticket):
    cfg = config.model_copy()
    arrived = time.monotonic() - epoch
    in_window = cfg.fault_start <= arrived < cfg.fault_start + cfg.fault_duration
    random_value = draw(cfg.seed, ticket.request_id, ticket.attempt, "fault")
    outage = cfg.scenario == "outage" and in_window
    hard_rate = {"error10": .1, "error30": .3, "error50": .5}.get(cfg.scenario, 0)
    hard_failure = outage or random_value < hard_rate
    soft_failure = in_window and random_value < cfg.soft_failure_rate
    delay = cfg.spike_latency if cfg.scenario == "latency" and in_window else cfg.latency

    fault_type, status = "none", 200
    if hard_failure:
        fault_type, status = ("outage" if outage else "server_error"), 503
    elif cfg.scenario == "rate_limit" and soft_failure:
        fault_type, status = "rate_limit", 429
    elif cfg.scenario in {"malformed", "empty", "irrelevant", "drift"} and soft_failure:
        fault_type = cfg.scenario

    event = dict(request_id=ticket.request_id, attempt=ticket.attempt,
                 arrived=arrived, during_outage=outage, fault_type=fault_type,
                 status=status, finished=None)
    events.append(event)
    await asyncio.sleep(delay)
    event["finished"] = time.monotonic() - epoch

    if status == 503:
        return JSONResponse(status_code=503, content={"detail": "Injected service failure"})
    if status == 429:
        return JSONResponse(status_code=429, content={"detail": "Injected rate limit"},
                            headers={"Retry-After": "1"})
    if fault_type == "malformed":
        return Response(content='{"label":', media_type="application/json")
    if fault_type == "empty":
        return Response(status_code=200)
    if fault_type == "irrelevant":
        return {"label": "other"}

    expected = dict(TICKETS).get(ticket.text, "unknown")
    if fault_type == "drift" and expected in LABELS:
        return {"label": LABELS[(LABELS.index(expected) + 1) % len(LABELS)]}
    return {"label": expected}
