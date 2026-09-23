# ทดลองความทนทานของ ML API แบบอ่านง่าย

ครอบคลุม A–D, outage, latency, 503 error 10/30/50%, 429, malformed/empty/irrelevant output, drift, metrics, raw data, กราฟ และร่างบทที่ 6–7 ใช้ Python 3.11 ขึ้นไป

## เริ่มใช้ในเครื่องนี้

เปิด PowerShell แล้วรัน:

```powershell
cd C:\se_g8
$pythonPath = (Get-ItemProperty 'HKCU:\Software\Python\PythonCore\3.11\InstallPath').ExecutablePath
& $pythonPath run_all.py
```

คำสั่งเดียวเปิด Mock API บน port ว่าง ทดสอบโค้ด รัน 11 scenarios × 4 strategies × 5 รอบ สร้างกราฟและรายงาน แล้วปิด server ของตัวเอง ผลแต่ละครั้งแยกโฟลเดอร์ใน results/ ไม่มีการเขียนทับผลก่อนหน้า

ถ้าต้องการสาธิตเร็วขึ้น ใช้ `& $pythonPath run_all.py --demo` (1 รอบ ไม่มี CI ที่ใช้สรุปสถิติได้)

## ติดตั้งในเครื่องอื่น

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_all.py
```

ต้องมี Python 3.11+ เพราะใช้ asyncio.timeout สำหรับ total deadline ต่อ attempt ไม่จำเป็นต้อง activate environment หากเรียก python.exe ตาม path

## อ่านโค้ดตามลำดับ

1. `app/common.py`: Ticket, ground truth, deterministic draw และ fallback hierarchy
2. `app/mock_api.py`: สร้างความผิดพลาดตามสถานการณ์
3. `app/strategies.py`: อ่าน no_protection → retry_only → circuit_breaker → circuit_breaker_with_fallback
4. `app/experiment.py`: warm-up, ตั้ง config, ส่ง workload และบันทึกข้อมูล
5. `app/analyze.py`: คำนวณ metrics และสร้างกราฟ
6. `app/report.py`: เติมผลจริงลงในบทที่ 6–7
7. `app/service.py`: Application API พร้อม bulkhead และข้อความ degraded mode
8. `run_all.py`: รวมคำสั่งทั้งหมดให้ใช้งานสะดวก

## A–D ทำงานอย่างไร

| Strategy | พฤติกรรม |
| --- | --- |
| A | เรียกครั้งเดียว มี timeout |
| B | เรียกรวมได้ 3 ครั้ง backoff + jitter เฉพาะ transient failure |
| C | Sliding window 10 calls, ขั้นต่ำ 5 calls, failure rate ≥ 50% จึงเปิด 1 วินาที แล้วลอง 1 probe |
| D | เหมือน C ถ้าไม่ได้ผล ใช้ fallback hierarchy |

Breaker นับ HTTP error, timeout และ schema/business validation failure ใน sliding window ใช้ generation token ป้องกันผลเก่าเปลี่ยนสถานะรุ่นใหม่ และยอมให้ half-open probe เพียงหนึ่ง request

HTTP 200 เป็นเพียง transport success; Pydantic ตรวจ valid output; experiment runner ตรวจ quality success เทียบ ground truth โดย breaker ไม่เห็นคำตอบเฉลย `human_review` ยังไม่นับเป็นความสำเร็จอัตโนมัติ กฎ fallback ครอบคลุมบางคำ เพื่อให้เห็นข้อแลกเปลี่ยนด้านคุณภาพ

`drift` ส่ง label ที่ schema ถูกแต่ผิด ground truth จึงเป็น silent failure ที่ตรวจพบในการประเมิน offline แต่ Breaker เปิดจากมันไม่ได้ในระบบจริงที่ไม่มีเฉลยทันที

## Fallback hierarchy และ Degraded Mode

Prototype ใช้ `Primary → simulated secondary → small/local rules → exact cache → semantic cache → rule-based → human_review` ทุกชั้นเป็น deterministic simulation เพื่อสาธิต control flow ไม่ใช่ provider/model/cache จริง ดูภาพใน `ARCHITECTURE.md`

สาธิต Application API โดยเปิด Mock API ที่ port 8000 และเปิดอีก terminal:

```powershell
& $pythonPath -m uvicorn app.service:app --port 8001
```

เรียก `POST http://127.0.0.1:8001/tickets/classify` ด้วย `{"text":"I need a refund"}` ผลมี `mode`, `source`, `fallback_tier` และข้อความสำหรับ UI เมื่อใช้ degraded mode ตัว service มี bulkhead จำกัดงาน Primary พร้อมกัน 20 รายการ

## ปรับการทดลองเอง

เปิด terminal แรก:

```powershell
& $pythonPath -m uvicorn app.mock_api:app
```

เปิด terminal ที่สอง ตั้ง `$pythonPath` อีกครั้ง แล้วรัน:

```powershell
& $pythonPath -m app.experiment --repeats 5 --duration 12 --rate 20
& $pythonPath -m app.analyze results\ชื่อโฟลเดอร์ที่โปรแกรมแสดง
```

server และ runner ต้องอยู่เครื่องเดียวกัน เพราะใช้ monotonic epoch ร่วมกัน ใช้ worker เดียว ห้ามเปิด reload ระหว่างวัดผล และรันทีละชุด `/config` เปลี่ยนสถานการณ์ ส่วน POST `/classify` รับ request_id, attempt, text เอกสาร API อยู่ /docs

## ผลลัพธ์ที่ใช้ในรายงาน

- `บทที่6-7.md`: วิธีทดลอง ตาราง กราฟ Discussion และข้อจำกัด
- `metrics_per_run.csv`: metrics ทุกชุดทดลอง
- `summary.csv`: mean, sample SD, 95% t-CI และจำนวนรอบที่มีข้อมูล
- `requests.json`: ผลสุดท้ายของทุก user request และ scheduler lag
- `attempts.json`: ทุก attempt, HTTP status, validation และเวลา
- `server_events.jsonl`: คำขอถึง server จริง รวมคำขอที่ client timeout
- `runs.json`, `config.json`, `environment.json`, `tickets.json`: ข้อมูลสำหรับทำซ้ำ
- `fallback_fixed_set.csv`, `fallback_fixed_metrics.json`: ทดสอบ fallback hierarchy บน Ticket ชุดเดียวกัน
- `failure_taxonomy_counts.csv`: จำนวน fault ที่ server สร้าง แยกตาม scenario/strategy
- รูป PNG: success, p50/p95/p99, primary calls, outage calls, recovery, cost, fallback accuracy และ timeline

## ข้อจำกัดที่ต้องพูดตอนพรีเซนต์

เป็น prototype บน 12 synthetic tickets ไม่ใช่ผลจาก LLM จริง Primary จำลองด้วย lookup ที่ถูกต้องเมื่อบริการพร้อม กฎ fallback แยกจาก ground truth ค่าใช้จ่ายเป็นหน่วยเงินสมมติ default 0.001 ต่อ dispatched attempt และ 0 ต่อ fallback ปรับได้ด้วย --cost-per-call และ --fallback-cost

ค่าเริ่มต้นแต่ละรอบส่ง 120 requests ใน 4 วินาที 5 รอบช่วยแสดงความผันผวน แต่ p99 ยังมีตัวอย่างน้อย ควรเพิ่ม duration/repeats สำหรับการศึกษาเข้มข้น CI ใช้รอบเป็นหน่วยและเป็น Student-t approximation ไม่ใช่ข้อพิสูจน์นัยสำคัญระหว่างวิธี

Latency รวมผลล้มเหลวด้วย อ่านควบคู่ success rate และ success_p95 เพื่อไม่ตีความ fast rejection เป็นประโยชน์ต่อผู้ใช้ Recovery เป็นการกลับมาเรียก Primary สำเร็จที่สังเกตครั้งแรก ไม่ใช่การพิสูจน์ว่าบริการเสถียรแล้ว N/A หมายถึงไม่มีข้อมูลที่วัดได้ ไม่ใช่ 0

Error rates เป็นความน่าจะเป็น สัดส่วนจริงอาจต่างจากค่าที่ตั้ง จับคู่ fault draw ด้วย seed/request ID/attempt; คำขอที่ retry เพิ่มหรือ breaker skip ย่อมทำให้ observed attempts ต่างกัน หมุนลำดับ A–D ในแต่ละรอบและ reset state หลัง warm-up ใช้ offered load เท่ากันและบันทึก scheduling lag Secondary/local/cache เป็น simulation และ human review ยังไม่มีเจ้าหน้าที่จริง

## ทดสอบโค้ด

```powershell
& $pythonPath test_core.py
# หรือเมื่อมี pytest
& $pythonPath -m pytest -q
```

ครอบคลุม deterministic fault, sliding window/half-open, fallback hierarchy, retry, circuit rejection, quality-aware breaker, 429, timeout และ fault taxonomy
