"""หน้าเว็บสาธิต degraded-mode UX โดยไม่ต้องติดตั้ง frontend framework."""

DEMO_HTML = r"""<!doctype html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Resilience Demo</title>
  <style>
    :root { font-family: system-ui, sans-serif; color: #172033; background: #eef2f7; }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 32px 16px; }
    main { max-width: 760px; margin: auto; }
    h1 { margin-bottom: 6px; }
    .subtitle { color: #596579; margin-top: 0; }
    .card { background: white; border-radius: 16px; padding: 22px; margin-top: 18px;
            box-shadow: 0 8px 30px #1d29391a; }
    label { display: block; font-weight: 650; margin: 12px 0 7px; }
    input, select, button { width: 100%; padding: 12px; border-radius: 9px;
                            border: 1px solid #bdc6d3; font: inherit; }
    button { margin-top: 16px; border: 0; background: #3157d5; color: white;
             font-weight: 700; cursor: pointer; }
    button:disabled { opacity: .6; cursor: wait; }
    .hint { color: #667085; font-size: 14px; }
    #result { border-left: 7px solid #98a2b3; }
    #result.normal { border-color: #17a673; background: #f0fff8; }
    #result.degraded { border-color: #f59e0b; background: #fff9e8; }
    #result.human_review { border-color: #3b82f6; background: #eff6ff; }
    #result.error { border-color: #dc2626; background: #fff1f2; }
    .badge { display: inline-block; border-radius: 999px; padding: 5px 10px;
             background: #e5e7eb; font-weight: 750; text-transform: uppercase; }
    .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 16px; }
    .metric { background: #ffffffaa; border: 1px solid #d8dee8; border-radius: 10px; padding: 12px; }
    .metric small { display: block; color: #667085; }
    @media (max-width: 620px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
<main>
  <h1>AI Degradation Lab</h1>
  <p class="subtitle">สาธิต Circuit Breaker + Fallback สำหรับระบบจัดหมวดหมู่ Ticket</p>
  <section class="card">
    <label for="scenario">Fault scenario (สำหรับการสาธิต)</label>
    <select id="scenario">
      <option value="normal">Normal</option>
      <option value="outage">HTTP 503 outage</option>
      <option value="rate_limit">HTTP 429 rate limit</option>
      <option value="malformed">Malformed JSON</option>
      <option value="empty">Empty output</option>
      <option value="irrelevant">Invalid label</option>
      <option value="drift">Silent drift (schema ถูก แต่คำตอบผิด)</option>
      <option value="latency">Latency spike</option>
    </select>
    <label for="ticket">Ticket</label>
    <input id="ticket" value="I need a refund" autocomplete="off">
    <p class="hint">ลอง “Please explain this invoice” เพื่อดูสถานะ Human Review</p>
    <button id="submit">จัดหมวดหมู่</button>
  </section>

  <section id="result" class="card" aria-live="polite">
    <span id="mode" class="badge">READY</span>
    <h2 id="message">พร้อมรับคำขอ</h2>
    <div class="grid">
      <div class="metric"><small>Label</small><strong id="label">—</strong></div>
      <div class="metric"><small>Source</small><strong id="source">—</strong></div>
      <div class="metric"><small>Fallback tier</small><strong id="tier">—</strong></div>
    </div>
  </section>
</main>
<script>
const button = document.querySelector('#submit');
const result = document.querySelector('#result');
let activeScenario = null;
const show = (mode, message, label='—', source='—', tier='—') => {
  result.className = 'card ' + mode;
  document.querySelector('#mode').textContent = mode;
  document.querySelector('#message').textContent = message;
  document.querySelector('#label').textContent = label;
  document.querySelector('#source').textContent = source;
  document.querySelector('#tier').textContent = tier || '—';
};
button.addEventListener('click', async () => {
  const text = document.querySelector('#ticket').value.trim();
  if (!text) return show('error', 'กรุณากรอกข้อความ Ticket');
  button.disabled = true;
  show('working', 'กำลังประมวลผล…');
  try {
    const selectedScenario = document.querySelector('#scenario').value;
    if (selectedScenario !== activeScenario) {
      await fetch('/demo/scenario', {
        method: 'PUT', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({scenario: selectedScenario})
      }).then(r => { if (!r.ok) throw new Error('ตั้งสถานการณ์ไม่สำเร็จ'); });
      activeScenario = selectedScenario;
    }
    const response = await fetch('/tickets/classify', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text})
    });
    if (!response.ok) throw new Error('เรียกบริการไม่สำเร็จ');
    const data = await response.json();
    show(data.mode, data.user_message, data.label, data.source, data.fallback_tier);
  } catch (error) {
    show('error', error.message + ' — ตรวจว่า Mock API เปิดอยู่ที่ port 8000');
  } finally { button.disabled = false; }
});
</script>
</body>
</html>"""
