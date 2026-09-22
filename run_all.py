"""คำสั่งเดียว: เปิด Mock API → ทดสอบ → ทดลอง → สร้างกราฟ/รายงาน → ปิด API."""
import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true', help='รัน 1 รอบ; ห้ามใช้สรุปสถิติ')
    args = parser.parse_args()
    # เลือก port ว่าง ไม่ใช้ server ของผู้ใช้ที่เปิดอยู่
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.mock_api:app',
                               '--port', str(port), '--log-level', 'warning'], cwd=ROOT)
    try:
        with httpx.Client(timeout=1, trust_env=False) as client:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError('Mock API could not start')
                try:
                    if client.get(url + '/openapi.json').status_code == 200:
                        break
                except httpx.RequestError:
                    time.sleep(.1)
            else:
                raise RuntimeError('Mock API readiness timeout')
        subprocess.run([sys.executable, 'test_core.py'], cwd=ROOT, check=True)
        subprocess.run([sys.executable, '-m', 'app.experiment', '--url', url,
                        '--repeats', '1' if args.demo else '5', '--duration', '4',
                        '--rate', '30', '--output', 'results'], cwd=ROOT, check=True)
        folders = [p for p in (ROOT / 'results').iterdir() if (p / 'config.json').exists()]
        folder = max(folders, key=lambda p: p.name)
        subprocess.run([sys.executable, '-m', 'app.analyze', str(folder)], cwd=ROOT, check=True)
        print(f'COMPLETE: {folder}', flush=True)
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()

if __name__ == '__main__':
    main()
