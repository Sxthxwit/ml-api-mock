import asyncio
import httpx
from app.common import draw, fallback
from app.strategies import Breaker, execute

def test_repeatable_faults():
    assert draw(42, 'ticket-1', 0, 'error') == draw(42, 'ticket-1', 0, 'error')
    assert draw(42, 'ticket-1', 0, 'error') != draw(42, 'ticket-1', 1, 'error')

def test_single_half_open_probe_and_stale_result():
    breaker = Breaker(threshold=1, cooldown=0)
    old = breaker.permit()
    breaker.record(old, False)
    probe = breaker.permit()
    assert probe is not None
    assert breaker.permit() is None
    breaker.record(old, True)
    assert breaker.state == 'half_open'
    breaker.record(probe, True)
    assert breaker.state == 'closed'

def test_human_review_is_not_classification():
    assert fallback('Please explain this invoice') == 'human_review'
    assert fallback('I need a refund') == 'billing'

def test_strategies():
    async def check():
        calls = []
        async def handler(request):
            calls.append(request)
            return httpx.Response(503, json={'detail': 'failure'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url='http://test') as client:
            a = await execute(client, 'A', Breaker(), '1', 'refund', 42, .3)
            b = await execute(client, 'B', Breaker(), '1', 'refund', 42, .3)
            assert len(a['attempts']) == 1 and len(b['attempts']) == 3
            breaker = Breaker(threshold=1)
            await execute(client, 'C', breaker, '1', 'refund', 42, .3)
            blocked = await execute(client, 'C', breaker, '2', 'refund', 42, .3)
            d = await execute(client, 'D', breaker, '3', 'refund', 42, .3)
            assert blocked['rejected'] and not blocked['attempts']
            assert d['label'] == 'billing' and d['source'] == 'fallback'
        async def malformed(request):
            return httpx.Response(200, content=b'{invalid')
        async with httpx.AsyncClient(transport=httpx.MockTransport(malformed), base_url='http://test') as client:
            result = await execute(client, 'B', Breaker(), '1', 'refund', 42, .3)
            assert len(result['attempts']) == 1  # malformed ไม่ retry
            assert result['label'] is None and result['attempts'][0]['transport_success']
            assert not result['attempts'][0]['valid_output']
    asyncio.run(check())

def test_timeout():
    async def check():
        async def slow(request):
            await asyncio.sleep(.2)
            return httpx.Response(200, json={'label': 'billing'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(slow), base_url='http://test') as client:
            result = await execute(client, 'A', Breaker(), '1', 'refund', 42, .01)
            assert result['label'] is None
            assert result['attempts'][0]['error'] == 'timeout_or_connection'
    asyncio.run(check())

if __name__ == '__main__':
    test_repeatable_faults()
    test_single_half_open_probe_and_stale_result()
    test_human_review_is_not_classification()
    test_strategies()
    test_timeout()
    print('5 core tests passed (also runnable with pytest)')
