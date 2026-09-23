# Architecture

```mermaid
flowchart LR
    UI[Client / UI] --> APP[Application API]
    APP --> BH[Bulkhead]
    BH --> REL[AI Reliability Layer]
    REL --> TO[Timeout]
    REL --> RT[Retry + Backoff + Jitter]
    REL --> CB[Sliding-window Quality-aware Circuit Breaker]
    REL --> VAL[Schema / Business Validation]
    CB --> PRIMARY[Primary Mock ML API]
    REL --> FC[Fallback Controller]
    FC --> SECONDARY[Simulated Secondary Provider]
    FC --> LOCAL[Small / Local Rules]
    FC --> CACHE[Exact Cache]
    FC --> SEM[Semantic Cache]
    FC --> RULES[Rule-based]
    FC --> HUMAN[Human Review]
    REL --> LOGS[Raw Events / Metrics]
    LOGS --> ANALYSIS[Pandas Analysis + Graphs]
```

`app/service.py` เป็น Application API สำหรับสาธิต degraded-mode response และ bulkhead ส่วน `app/experiment.py` เรียก Reliability Layer โดยตรงเพื่อควบคุมการทดลอง A–D ทุกชั้น fallback ใน prototype เป็น deterministic simulation ไม่มี provider/model/cache ภายนอกจริง จึงใช้ศึกษา control flow และ trade-off ไม่ใช่ benchmark ความแม่นยำของ LLM จริง
