import asyncio
import time
from typing import Literal
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from app.common import TICKETS, draw

app = FastAPI(title='Resilience Lab Mock API')

class Config(BaseModel):
    # ตั้งสถานการณ์ผ่าน PUT /config ก่อนเริ่มแต่ละรอบ
    scenario: Literal['normal', 'outage', 'latency', 'error10', 'error30', 'error50'] = 'normal'
    seed: int = 42
    start_delay: float = Field(default=0.2, ge=0)
    fault_start: float = Field(default=3, ge=0)
    fault_duration: float = Field(default=4, gt=0)
    latency: float = Field(default=0.02, ge=0)
    spike_latency: float = Field(default=0.8, ge=0)

class Ticket(BaseModel):
    request_id: str
    attempt: int = Field(default=0, ge=0)
    text: str

config = Config()
epoch = time.monotonic()
events = []

@app.put('/config')
async def configure(value: Config):
    global config, epoch
    config = value
    epoch = time.monotonic() + value.start_delay
    events.clear()
    # ตัว runner และ server อยู่เครื่องเดียวกัน จึงใช้ monotonic epoch ร่วมกันได้
    return {'config': value.model_dump(), 'epoch': epoch}

@app.get('/events')
async def get_events():
    return events

@app.post('/classify')
async def classify(ticket: Ticket):
    cfg = config.model_copy()
    arrived = time.monotonic() - epoch
    in_window = cfg.fault_start <= arrived < cfg.fault_start + cfg.fault_duration
    outage = cfg.scenario == 'outage' and in_window
    rate = {'error10': .1, 'error30': .3, 'error50': .5}.get(cfg.scenario, 0)
    failed = outage or draw(cfg.seed, ticket.request_id, ticket.attempt, 'error') < rate
    delay = cfg.spike_latency if cfg.scenario == 'latency' and in_window else cfg.latency
    # Record arrival before sleeping, including calls whose clients time out.
    event = dict(request_id=ticket.request_id, attempt=ticket.attempt,
                 arrived=arrived, during_outage=outage, status=503 if failed else 200,
                 finished=None)
    events.append(event)
    await asyncio.sleep(delay)
    event['finished'] = time.monotonic() - epoch
    if failed:
        return JSONResponse(status_code=503, content={'detail': 'Injected failure'})
    # Perfect fixture lookup isolates service resilience from model errors.
    label = dict(TICKETS).get(ticket.text, 'unknown')
    return {'label': label}
