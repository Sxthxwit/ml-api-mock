"""สร้างร่างบทที่ 6–7 จากตัวเลขจริง โดยไม่ต้องคัดลอกตัวเลขด้วยมือ."""
import json
import pandas as pd

def markdown_table(frame):
    lines = ['| ' + ' | '.join(frame.columns) + ' |', '| ' + ' | '.join(['---'] * len(frame.columns)) + ' |']
    for row in frame.itertuples(index=False, name=None):
        cells = []
        for value in row:
            if pd.isna(value):
                cells.append('N/A')
            elif isinstance(value, (int, float)):
                cells.append(f'{value:.4f}')
            else:
                cells.append(str(value))
        lines.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join(lines)

def write_report(folder, metrics, summary, config, fixed):
    means = metrics.groupby(['scenario', 'strategy']).mean(numeric_only=True).reset_index()
    env = json.loads((folder / 'environment.json').read_text(encoding='utf-8'))
    n = int(config['duration'] * config['rate'])
    total = n * len(metrics)
    main = means[['scenario', 'strategy', 'success_rate', 'p50', 'p95', 'p99']]
    extra = means[['scenario', 'strategy', 'primary_calls', 'requests_during_outage', 'recovery_seconds', 'estimated_cost_per_request', 'fallback_accuracy']]
    text = f'''# บทที่ 6 Experiment & Evaluation

ผู้รับผิดชอบ: @chrisfoong และ นายเศรษฐวิทย์ ชัยรัตนานนท์ (@sxthawit)

## 6.1 วัตถุประสงค์และกลยุทธ์

ศึกษาว่า Circuit Breaker ร่วมกับ Fallback เปลี่ยนอัตราคำตอบที่ถูกต้อง เวลาในการตอบสนอง ภาระการเรียก API และต้นทุนสมมติอย่างไร เมื่อเทียบกับการเรียกครั้งเดียวและ Retry อย่างเดียว

| วิธี | พฤติกรรม |
| --- | --- |
| A | เรียก Primary ครั้งเดียว มี timeout ไม่มี retry |
| B | รวมไม่เกิน 3 attempts; exponential backoff 0.05 × 2^attempt วินาที คูณ jitter ระหว่าง 0–1 |
| C | Circuit Breaker: failure ติดต่อกัน 3 ครั้ง เปิด 1 วินาที แล้วอนุญาต probe 1 ครั้ง ไม่มี retry |
| D | เหมือน C และใช้ keyword fallback ถ้า Primary ใช้งานไม่ได้หรือวงจรเปิด |

ทุกวิธีใช้ deadline ต่อ attempt {config['timeout']} วินาที และ connection pool สูงสุด 200 connections โดยไม่มี end-to-end SLA แยกต่างหากในรุ่นนี้ ค่า latency รวมเวลารอ retry และ fallback ภายใน request นั้น

## 6.2 สถานการณ์และวิธีดำเนินการ

ทดลอง 6 สถานการณ์: normal, outage, latency spike, error 10%, 30%, 50% กรณี error ใช้ HTTP 503 เท่านั้น โหมดปกติหน่วง 0.02 วินาที; spike หน่วง 0.8 วินาที ช่วง outage/spike เริ่มที่ 25% ของระยะเวลาทดลอง และกินเวลา 35% จึงกลับเป็นปกติที่ 60% ของระยะเวลาทดลอง ความล้มเหลวตัดสินจากเวลาที่ server รับ attempt

การรันนี้ใช้ {config['repeats']} รอบต่อ strategy/scenario ระยะส่ง request รอบละ {config['duration']} วินาที อัตรา {config['rate']} requests/วินาที จึงมี {n} user requests ต่อชุด รวม {len(metrics)} ชุด หรือ {total:,} user requests ไม่รวม warm-up และ retry

ก่อนแต่ละชุดยิง warm-up 5 ครั้งในโหมดปกติ แล้ว reset config, events และ breaker state ข้อมูล warm-up ไม่รวมใน metrics ใช้ Ticket จำลอง 12 ข้อที่ระบุ label ไว้และวนลำดับเดิมในทุกวิธี ระบบส่ง request ตามตารางเวลาโดยไม่รอ request ก่อนหน้าจบ จึงไม่ลด offered load เมื่อ strategy ตอบช้า บันทึก scheduler lag ไว้ตรวจข้อจำกัดของเครื่อง

ใช้ seed 42 ถึง {42 + config['repeats'] - 1}; seed, request ID และ attempt เดียวกันให้ fault draw เดียวกัน ต่าง seed ระหว่างรอบ หมุนลำดับกลยุทธ์เพื่อลดอคติจากการรันวิธีเดิมก่อนทุกครั้ง rate ที่กำหนดเป็นความน่าจะเป็น สัดส่วนจริงในชุดเล็กอาจต่างจาก 10/30/50% และ strategy ที่ skip/retry จะเห็นชุด attempts ต่างกัน

Mock API และ runner รันเครื่องเดียวกัน worker เดียว ใช้ monotonic clock ร่วมกัน Python {env['python']}; platform: {env['platform']} รายละเอียดแพ็กเกจอยู่ใน environment.json และพารามิเตอร์อยู่ใน config.json

## 6.3 นิยาม Metrics

| Metric | นิยาม |
| --- | --- |
| Transport success | attempt ได้ HTTP 200 |
| Valid output | label ผ่าน Pydantic schema อยู่ใน billing/account/technical |
| User-visible success | คำตอบสุดท้ายตรง ground truth ÷ user requests ทั้งหมด |
| Primary/Fallback success | แยกแหล่งคำตอบถูกต้อง ใช้ user requests ทั้งหมดเป็นตัวหาร |
| p50/p95/p99 | quantile ของ latency ทุก user request รวมคำตอบล้มเหลวและ circuit rejection |
| success_p95 | p95 เฉพาะคำตอบถูกต้อง ใช้อ่านประกอบเพื่อไม่ให้ fast failure ดูดีเกินจริง |
| Recovery time | จาก outage สิ้นสุดถึง primary attempt ที่เริ่มหลัง outage และผ่าน validation สำเร็จครั้งแรก |
| Requests during outage | จำนวน attempts ที่ถึง server ภายใน outage ตาม server arrival log |
| Estimated cost/request | (จำนวน dispatched attempts × {config['cost_per_call']} + จำนวน fallback × {config['fallback_cost']}) ÷ user requests |
| Fallback quality | accuracy, macro precision/recall/F1; human_review นับว่าไม่สำเร็จอัตโนมัติ |
| Circuit-open duration | รวมเวลาสถานะ open ระหว่างวัดผล ไม่รวม half-open |

ต้นทุนใช้หน่วยเงินสมมติ ไม่ใช่ราคาจริงของผู้ให้บริการและไม่ได้คำนวณ token Recovery ที่ไม่สังเกตพบหรือกรณีไม่มี fallback ใช้ N/A ไม่แทนด้วยศูนย์

คำนวณ metrics ต่อรอบก่อน แล้วรายงาน mean, sample SD และ 95% Student-t confidence interval ข้ามรอบใน summary.csv ไม่ถือว่า request ที่พึ่งพาสถานะ breaker แต่ละรายการเป็นตัวอย่างอิสระสำหรับ CI กรณีมีเพียงรอบเดียวไม่มี SD/CI ที่ใช้ได้ ช่วง CI ของสัดส่วนอาจออกนอก 0–1 จากวิธี t approximation

# บทที่ 7 Results & Discussion

ผลต่อไปนี้สร้างจาก raw data ในโฟลเดอร์เดียวกับรายงาน ไม่มีการเติมตัวเลขสมมติลงในผลการรัน

## 7.1 ความสำเร็จและ Latency

ตัวเลข success_rate เป็นสัดส่วน 0–1; latency เป็นวินาที ตารางเป็นค่าเฉลี่ยของ metric แต่ละรอบ ไม่ใช่ percentile จากการรวมทุก request เข้าด้วยกัน

{markdown_table(main)}

![Success rate](success_rate.png)

![p95 latency](p95.png)

กราฟ p50.png และ p99.png แสดง percentile เพิ่มเติม; error bars แสดง CI ข้ามรอบ

## 7.2 ภาระ API การฟื้นตัว ต้นทุน และ Fallback

{markdown_table(extra)}

![Primary calls](primary_calls.png)

![Recovery](recovery_seconds.png)

![Outage traffic](outage_timeline.png)

outage_timeline.png แสดงรอบแรกเพื่ออธิบายพฤติกรรมเท่านั้น ไม่ใช่ผลเฉลี่ยทุกรอบ ตาราง summary.csv เป็นข้อมูลสำหรับสรุปผลซ้ำ

## 7.3 คุณภาพ Fallback บนชุดคงที่

เมื่อทดสอบ Fallback บน Ticket ทั้ง {fixed['n']} ข้อเดียวกัน ได้ accuracy {fixed['accuracy']:.4f}, macro precision {fixed['macro_precision']:.4f}, macro recall {fixed['macro_recall']:.4f}, macro-F1 {fixed['macro_f1']:.4f} และ coverage {fixed['coverage']:.4f} รายละเอียดแต่ละข้ออยู่ใน fallback_fixed_set.csv

การประเมินชุดคงที่นี้ช่วยแยกความสามารถของกฎสำรองออกจากผลของ breaker ที่เลือกส่ง Ticket บางส่วนมาเข้า Fallback ขณะที่ fallback_accuracy ในตารางด้านบนวัดเฉพาะ Ticket ที่ใช้ Fallback จริงในแต่ละรอบ การส่ง human_review ยังไม่รวมเวลาทำงานของคนและไม่นับเป็นคำตอบอัตโนมัติสำเร็จ

## 7.4 Trade-offs จากผลที่สังเกต

'''
    for scenario in ['outage', 'latency', 'error50']:
        group = means[means.scenario == scenario].set_index('strategy')
        if not all(s in group.index for s in 'ABCD'):
            continue
        a, b, c, d = (group.loc[s] for s in 'ABCD')
        text += (f"- {scenario}: B เรียก Primary เฉลี่ย {b.primary_calls:.1f} ครั้ง เทียบ A {a.primary_calls:.1f} ครั้ง; "
                 f"C เรียก {c.primary_calls:.1f} ครั้ง แต่ success rate เท่ากับ {c.success_rate:.3f}; "
                 f"D มี success rate {d.success_rate:.3f} เทียบ C {c.success_rate:.3f} "
                 f"และ p95 ของ D/B เท่ากับ {d.p95:.4f}/{b.p95:.4f} วินาทีตามลำดับ\n")
    text += '''
Retry เพิ่มโอกาสผ่าน transient error แต่ใช้จำนวน attempts และเวลารอเพิ่ม Breaker อาจลดคำขอในช่วงล่มพร้อมกับปฏิเสธคำขอที่ยังพอสำเร็จได้ โดยเฉพาะ error แบบสุ่ม Fallback ให้ประโยชน์เท่าที่กฎสำรองครอบคลุม การตอบเร็วจากการปฏิเสธ request จึงไม่ใช่ความสำเร็จของผู้ใช้ ต้องอ่าน latency ควบคู่กับ success rate และคุณภาพเสมอ ผลเชิงพรรณนานี้ยังไม่ใช่การทดสอบนัยสำคัญทางสถิติระหว่างวิธี

## 7.5 ข้อจำกัดและงานต่อยอด

ใช้ API จำลองและ Ticket 12 ข้อ ไม่ใช่โมเดลจริง Primary ใช้ fixture lookup ที่ถูกต้องเสมอเมื่อบริการพร้อมเพื่อแยกผล service failure ออกจาก model quality; Fallback ใช้กฎบางส่วน ไม่ได้สร้าง ground truth ด้วยกฎเดียวกัน จึงห้ามอ้างว่าผลนี้เป็นความแม่นยำของ LLM จริง รอบทดลองสั้นและจำนวนตัวอย่าง tail latency จำกัด ควรเพิ่ม duration/repeats และใช้ข้อมูลจริงก่อนสรุปทั่วไป

ยังไม่จำลอง 429, malformed output หรือ drift ในชุด 6 scenarios นี้ ไม่มี secondary provider หรือ human review ที่ทำงานจริง ค่าใช้จ่ายเป็นสมมติ การแบ่ง success ตาม ground truth ทำได้ offline ในการทดลอง แต่ระบบ production อาจไม่มีคำตอบเฉลยใช้ตรวจทันที

ภาคผนวก: requests.json (ผลผู้ใช้), attempts.json (ทุกครั้งที่เรียก), server_events.jsonl (server arrival), runs.json (สถานะต่อชุด), metrics_per_run.csv, summary.csv, config.json, environment.json, tickets.json และ source code ใน app/
'''
    (folder / 'บทที่6-7.md').write_text(text, encoding='utf-8')
