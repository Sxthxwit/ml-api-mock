import asyncio
import json
import httpx

from app.common import draw, fallback_hierarchy
from app.mock_api import Config, Ticket, classify, configure
from app.strategies import Breaker, execute
from app import service


def test_repeatable_faults():
    assert draw(42, "ticket-1", 0, "error") == draw(42, "ticket-1", 0, "error")
    assert draw(42, "ticket-1", 0, "error") != draw(42, "ticket-1", 1, "error")


def test_sliding_window_and_half_open():
    breaker = Breaker(window_size=5, minimum_calls=5, failure_rate_threshold=.6, cooldown=0)
    tokens = [breaker.permit() for _ in range(5)]
    for token, success in zip(tokens, [True, False, False, True, False]):
        breaker.record(token, success)
    assert breaker.state == "open" and breaker.failure_rate == .6
    probe = breaker.permit()
    assert probe is not None and breaker.state == "half_open"
    assert breaker.permit() is None
    breaker.record(probe, True)
    assert breaker.state == "closed" and not breaker.outcomes


def test_fallback_hierarchy():
    assert fallback_hierarchy("Change my email address") == ("account", "secondary_provider")
    assert fallback_hierarchy("I was charged twice") == ("billing", "small_local_model")
    assert fallback_hierarchy("I need a refund") == ("billing", "cache")
    assert fallback_hierarchy("Please explain this invoice") == ("human_review", "human_review")
    assert fallback_hierarchy("The screen stays blank") == ("human_review", "human_review")
    assert fallback_hierarchy("Completely new request") == ("human_review", "human_review")


def test_strategies_and_quality_aware_breaker():
    async def check():
        async def failure(request):
            return httpx.Response(503, json={"detail": "failure"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(failure), base_url="http://test") as client:
            a = await execute(client, "A", Breaker(), "1", "refund", 42, .3)
            b = await execute(client, "B", Breaker(), "1", "refund", 42, .3)
            assert len(a["attempts"]) == 1 and len(b["attempts"]) == 3
            breaker = Breaker(minimum_calls=1, failure_rate_threshold=1)
            await execute(client, "C", breaker, "1", "refund", 42, .3)
            blocked = await execute(client, "C", breaker, "2", "refund", 42, .3)
            d = await execute(client, "D", breaker, "3", "I need a refund", 42, .3)
            assert blocked["rejected"] and not blocked["attempts"]
            assert d["label"] == "billing" and d["fallback_tier"] == "cache"

        async def malformed(request):
            return httpx.Response(200, content=b"{invalid")
        async with httpx.AsyncClient(transport=httpx.MockTransport(malformed), base_url="http://test") as client:
            breaker = Breaker(minimum_calls=1, failure_rate_threshold=1)
            result = await execute(client, "C", breaker, "1", "refund", 42, .3)
            assert result["attempts"][0]["transport_success"]
            assert not result["attempts"][0]["valid_output"]
            assert breaker.state == "open"

        calls = 0
        async def rate_limited(request):
            nonlocal calls
            calls += 1
            return httpx.Response(429, json={"detail": "slow down"}, headers={"Retry-After": "0"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(rate_limited), base_url="http://test") as client:
            await execute(client, "B", Breaker(), "1", "refund", 42, .3)
            assert calls == 3
    asyncio.run(check())


def test_timeout():
    async def check():
        async def slow(request):
            await asyncio.sleep(.2)
            return httpx.Response(200, json={"label": "billing"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(slow), base_url="http://test") as client:
            result = await execute(client, "A", Breaker(), "1", "refund", 42, .01)
            assert result["attempts"][0]["error"] == "timeout_or_connection"
    asyncio.run(check())


def test_mock_failure_taxonomy():
    async def check():
        ticket = Ticket(request_id="1", text="I need a refund")
        for scenario in ["rate_limit", "malformed", "empty", "irrelevant", "drift"]:
            await configure(Config(scenario=scenario, start_delay=0, fault_start=0,
                                   fault_duration=100, latency=0, soft_failure_rate=1))
            response = await classify(ticket)
            if scenario == "rate_limit":
                assert response.status_code == 429
            elif scenario == "malformed":
                assert response.body == b'{"label":'
            elif scenario == "empty":
                assert response.status_code == 200 and not response.body
            elif scenario == "irrelevant":
                assert response == {"label": "other"}
            elif scenario == "drift":
                assert response["label"] != "billing"
    asyncio.run(check())


def test_degraded_service_response():
    async def check():
        async def unavailable(request):
            return httpx.Response(503, json={"detail": "failure"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable),
                                     base_url="http://test") as client:
            service.app.state.client = client
            service.breaker = Breaker()
            response = await service.classify_ticket(service.TicketRequest(text="I need a refund"))
            assert response.label == "billing"
            assert response.source == "fallback"
            assert response.mode == "degraded"
            assert response.user_message
    asyncio.run(check())


if __name__ == "__main__":
    tests = [test_repeatable_faults, test_sliding_window_and_half_open,
             test_fallback_hierarchy, test_strategies_and_quality_aware_breaker,
             test_timeout, test_mock_failure_taxonomy, test_degraded_service_response]
    for test in tests:
        test()
    print(f"{len(tests)} core tests passed (also runnable with pytest)")
