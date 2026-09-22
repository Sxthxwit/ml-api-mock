import argparse
import asyncio
import json
import time
import platform
from importlib.metadata import distributions
from datetime import datetime
from pathlib import Path
import httpx
from app.common import TICKETS
from app.strategies import Breaker, execute

async def run(args):
    output = Path(args.output) / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output.mkdir(parents=True)
    (output / 'config.json').write_text(json.dumps(vars(args), indent=2), encoding='utf-8')
    (output / 'environment.json').write_text(json.dumps(dict(python=platform.python_version(),
        platform=platform.platform(), packages={d.metadata['Name']: d.version for d in distributions()}), indent=2), encoding='utf-8')
    (output / 'tickets.json').write_text(json.dumps(TICKETS, indent=2), encoding='utf-8')
    records, attempts, runs = [], [], []
    async with httpx.AsyncClient(base_url=args.url, timeout=5, trust_env=False, limits=httpx.Limits(max_connections=200)) as client:
        for scenario in args.scenarios:
            for repeat in range(args.repeats):
                seed = 42 + repeat
                # หมุนลำดับเพื่อลดผลจากการรัน A ก่อนทุกครั้ง
                order = 'ABCD'[repeat % 4:] + 'ABCD'[:repeat % 4]
                for strategy in order:
                    # Warm-up has its own normal config and no measured breaker state.
                    response = await client.put('/config', json={'scenario': 'normal'})
                    response.raise_for_status()
                    for i in range(5):
                        await client.post('/classify', json={'request_id': f'warm-{i}', 'text': TICKETS[0][0]})
                    configuration = dict(scenario=scenario, seed=seed, start_delay=.3,
                                         fault_start=args.duration * .25, fault_duration=args.duration * .35)
                    response = await client.put('/config', json=configuration)
                    response.raise_for_status()
                    breaker = Breaker()
                    epoch = response.json()['epoch']
                    tag = dict(scenario=scenario, repeat=repeat, strategy=strategy)
                    async def one(i):
                        scheduled = i / args.rate
                        await asyncio.sleep(max(0, epoch + scheduled - time.monotonic()))
                        text, expected = TICKETS[i % len(TICKETS)]
                        actual_start = time.monotonic() - epoch
                        result = await execute(client, strategy, breaker, str(i), text, seed, args.timeout)
                        finished = time.monotonic() - epoch
                        for item in result.pop('attempts'):
                            item['started'] -= epoch
                            item['finished'] -= epoch
                            attempts.append(dict(**tag, request_id=str(i), **item))
                        records.append(dict(**tag, request_id=str(i), scheduled=scheduled, finished=finished,
                                            scheduler_lag=max(0, actual_start - scheduled),
                                            expected=expected, quality_success=result['label'] == expected,
                                            **result))
                    await asyncio.gather(*(one(i) for i in range(int(args.duration * args.rate))))
                    open_duration = breaker.duration()
                    # Allow server-side work to finish after client timeouts before reconfiguring.
                    await asyncio.sleep(.85 if scenario == 'latency' else .03)
                    response = await client.get('/events')
                    response.raise_for_status()
                    events = response.json()
                    runs.append(dict(**tag, config=configuration, circuit_open_seconds=open_duration,
                                     server_requests=len(events), requests_during_outage=sum(e['during_outage'] for e in events)))
                    with (output / 'server_events.jsonl').open('a', encoding='utf-8') as file:
                        for event in events:
                            file.write(json.dumps(dict(**tag, **event)) + '\n')
                    print(f'{scenario} round={repeat + 1} strategy={strategy} calls={len(events)}', flush=True)
                    # Checkpoint each run so an interruption does not discard completed results.
                    for name, data in [('requests', records), ('attempts', attempts), ('runs', runs)]:
                        (output / f'{name}.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    print(f'Results: {output.resolve()}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--output', default='results')
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--duration', type=float, default=4)
    parser.add_argument('--rate', type=float, default=30)
    parser.add_argument('--timeout', type=float, default=.3)
    parser.add_argument('--cost-per-call', type=float, default=.001)
    parser.add_argument('--fallback-cost', type=float, default=0)
    parser.add_argument('--scenarios', nargs='+', choices=['normal', 'outage', 'latency', 'error10', 'error30', 'error50'], default=['normal', 'outage', 'latency', 'error10', 'error30', 'error50'])
    args = parser.parse_args()
    if min(args.repeats, args.duration, args.rate, args.timeout) <= 0 or int(args.duration * args.rate) < 1 or min(args.cost_per_call, args.fallback_cost) < 0:
        parser.error('repeats, duration, rate and timeout must be positive')
    asyncio.run(run(args))
