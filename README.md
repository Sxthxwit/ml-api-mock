# ทดลองความทนทานของ ML API แบบอ่านง่าย

ครอบคลุมงาน Experiment / Data: A–D, API outage, latency spike, error 10/30/50%, metrics, raw data, กราฟ และร่างบทที่ 6–7 จากผลจริง ใช้ Python 3.11 ขึ้นไป

## เริ่มใช้ในเครื่องนี้

เปิด PowerShell แล้วรัน:

```powershell
cd C:\se_g8
$pythonPath = (Get-ItemProperty 'HKCU:\Software\Python\PythonCore\3.11\InstallPath').ExecutablePath
& $pythonPath run_all.py
```

คำสั่งเดียวเปิด Mock API บน port ว่าง ทดสอบโค้ด รัน 6 scenarios × 4 strategies × 5 รอบ สร้างกราฟและรายงาน แล้วปิด server ของตัวเอง ใช้เวลาประมาณ 10 นาที ผลแต่ละครั้งแยกโฟลเดอร์ใน results/ ไม่มีการเขียนทับผลก่อนหน้า

ถ้าต้องการสาธิตเร็วขึ้น ใช้ `& $pythonPath run_all.py --demo` (1 รอบ ไม่มี CI ที่ใช้สรุปสถิติได้)

## ติดตั้งในเครื่องอื่น

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_all.py
```

ต้องมี Python 3.11+ เพราะใช้ asyncio.timeout สำหรับ total deadline ต่อ attempt ไม่จำเป็นต้อง activate environment หากเรียก python.exe ตาม path

## อ่านโค้ดตามลำดับ

1. `app/common.py`: Ticket พร้อม ground truth, deterministic draw และกฎ fallback
2. `app/mock_api.py`: สร้างความผิดพลาดตามสถานการณ์
3. `app/strategies.py`: อ่าน no_protection → retry_only → circuit_breaker → circuit_breaker_with_fallback
4. `app/experiment.py`: warm-up, ตั้ง config, ส่ง workload และบันทึกข้อมูล
5. `app/analyze.py`: คำนวณ metrics และสร้างกราฟ
6. `app/report.py`: เติมผลจริงลงในบทที่ 6–7
7. `run_all.py`: รวมคำสั่งทั้งหมดให้ใช้งานสะดวก

## A–D ทำงานอย่างไร

| Strategy | พฤติกรรม |
| --- | --- |
| A | เรียกครั้งเดียว มี timeout |
| B | เรียกรวมได้ 3 ครั้ง backoff + jitter เฉพาะ transient failure |
| C | ครบ 3 failures ติดต่อกัน เปิดวงจร 1 วินาที แล้วลอง 1 probe |
| D | เหมือน C ถ้าไม่ได้ผล ใช้ keyword fallback |

Breaker state ใช้ generation token ป้องกัน request เก่าที่กำลังรออยู่เปลี่ยนสถานะของวงจรรุ่นใหม่ และยอมให้ probe ใน half-open ได้เพียงหนึ่งครั้งใน worker นี้ ส่วนนี้จำเป็นเมื่อใช้ concurrent requests

HTTP 200 เป็นเพียง transport success; Pydantic ตรวจ valid output; experiment runner ตรวจ quality success เทียบ ground truth โดย breaker ไม่เห็นคำตอบเฉลย `human_review` ยังไม่นับเป็นความสำเร็จอัตโนมัติ กฎ fallback ครอบคลุมบางคำ เพื่อให้เห็นข้อแลกเปลี่ยนด้านคุณภาพ

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
- `fallback_fixed_set.csv`, `fallback_fixed_metrics.json`: ทดสอบ fallback บน Ticket ทั้งชุดเดียวกัน
- รูป PNG: success, p50/p95/p99, primary calls, outage calls, recovery, cost, fallback accuracy และ timeline

## ข้อจำกัดที่ต้องพูดตอนพรีเซนต์

เป็น prototype บน 12 synthetic tickets ไม่ใช่ผลจาก LLM จริง Primary จำลองด้วย lookup ที่ถูกต้องเมื่อบริการพร้อม กฎ fallback แยกจาก ground truth ค่าใช้จ่ายเป็นหน่วยเงินสมมติ default 0.001 ต่อ dispatched attempt และ 0 ต่อ fallback ปรับได้ด้วย --cost-per-call และ --fallback-cost

ค่าเริ่มต้นแต่ละรอบส่ง 120 requests ใน 4 วินาที 5 รอบช่วยแสดงความผันผวน แต่ p99 ยังมีตัวอย่างน้อย ควรเพิ่ม duration/repeats สำหรับการศึกษาเข้มข้น CI ใช้รอบเป็นหน่วยและเป็น Student-t approximation ไม่ใช่ข้อพิสูจน์นัยสำคัญระหว่างวิธี

Latency รวมผลล้มเหลวด้วย อ่านควบคู่ success rate และ success_p95 เพื่อไม่ตีความ fast rejection เป็นประโยชน์ต่อผู้ใช้ Recovery เป็นการกลับมาเรียก Primary สำเร็จที่สังเกตครั้งแรก ไม่ใช่การพิสูจน์ว่าบริการเสถียรแล้ว N/A หมายถึงไม่มีข้อมูลที่วัดได้ ไม่ใช่ 0

Error rates เป็นความน่าจะเป็น สัดส่วนจริงอาจต่างจากค่าที่ตั้ง จับคู่ fault draw ด้วย seed/request ID/attempt; คำขอที่ retry เพิ่มหรือ breaker skip ย่อมทำให้ observed attempts ต่างกัน หมุนลำดับ A–D ในแต่ละรอบและ reset state หลัง warm-up ใช้ offered load เท่ากันและบันทึก scheduling lag

## ทดสอบโค้ด

```powershell
& $pythonPath test_core.py
# หรือเมื่อมี pytest
& $pythonPath -m pytest -q
```

ครอบคลุม deterministic fault, stale result/half-open, human review, จำนวน retries, circuit rejection, fallback, malformed output ไม่ retry และ timeout
