import asyncio
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import vocabulary as vocab


class NormalizationTests(unittest.TestCase):
    def test_original_notebook_export(self):
        payload = {"app": "word-notebook", "words": [{"word": " resilient ",
                   "zhGroups": [{"pos": "adjective", "text": "有韧性的"}],
                   "createdAt": 1791244800000, "audio": "javascript:alert(1)"}]}
        word = vocab.normalize_words(payload)[0]
        self.assertEqual(word["word"], "resilient")
        self.assertEqual(word["zhGroups"][0]["text"], "有韧性的")
        self.assertNotIn("audio", word)

    def test_empty_array_is_valid(self):
        self.assertEqual(vocab.normalize_words([]), [])
        self.assertEqual(vocab.normalize_words({"words": []}), [])

    def test_invalid_payload_does_not_silently_drop_rows(self):
        for payload in ({}, {"words": {}}, ["word"], [{"word": " "}],
                        [{"word": "hello", "zh": {}}], [{"word": "hello", "zhGroups": [4]}]):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                vocab.normalize_words(payload)

    def test_invalid_dates_are_not_rendered(self):
        for value in (None, "bad", float("nan"), float("inf"), True, -1):
            self.assertIsNone(vocab.normalize_words([{"word": "hello", "createdAt": value}])[0]["createdAt"])

    def test_limits(self):
        with self.assertRaises(ValueError):
            vocab.normalize_words([{"word": "x"}] * 10001)


class FeedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.feed = vocab.VocabularyFeed()
        self.calls = []
        self.replies = []
        real_client = httpx.AsyncClient

        def handle(request):
            self.calls.append(request)
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        transport = httpx.MockTransport(handle)
        self.mock = patch.object(vocab.httpx, "AsyncClient", side_effect=lambda **kw: real_client(transport=transport, **kw))
        self.mock.start()
        self.addCleanup(self.mock.stop)

    async def first_sync(self):
        self.replies.append(httpx.Response(200, json={"words": [{"word": "first", "zh": "最初"}]}, headers={"etag": '"v1"'}))
        return await self.feed.snapshot()

    async def test_concurrent_requests_share_one_fetch(self):
        self.replies.append(httpx.Response(200, json=[{"word": "shared"}]))
        results = await asyncio.gather(*[self.feed.snapshot() for _ in range(10)])
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(all(r["words"][0]["word"] == "shared" and not r["stale"] for r in results))

    async def test_etag_304_retains_snapshot(self):
        first = await self.first_sync()
        self.feed.next_check = 0
        self.replies.append(httpx.Response(304))
        second = await self.feed.snapshot()
        self.assertEqual(self.calls[-1].headers["if-none-match"], '"v1"')
        self.assertEqual(second["words"], first["words"])
        self.assertFalse(second["stale"])

    async def test_remote_update_then_empty_feed(self):
        await self.first_sync()
        for payload in ([{"word": "new"}], []):
            self.feed.next_check = 0
            self.replies.append(httpx.Response(200, json=payload))
            result = await self.feed.snapshot()
            self.assertEqual(result["words"], vocab.normalize_words(payload))
            self.assertTrue(result["available"])

    async def test_invalid_update_retains_last_good_data(self):
        first = await self.first_sync()
        for reply in (httpx.Response(200, content=b"not json"), httpx.Response(200, json={"words": [{}]}),
                      httpx.Response(404), httpx.Response(429), httpx.ConnectError("offline"),
                      httpx.Response(200, content=b" " * (vocab.MAX_BYTES + 1))):
            self.feed.next_check = 0
            self.replies.append(reply)
            result = await self.feed.snapshot()
            self.assertTrue(result["stale"])
            self.assertEqual(result["words"], first["words"])
            self.assertEqual(result["checkedAt"], first["checkedAt"])
            self.assertEqual(self.feed.etag, '"v1"')

    async def test_initial_failure_is_not_empty_success_and_is_cached(self):
        self.replies.append(httpx.Response(404))
        result = await self.feed.snapshot()
        await self.feed.snapshot()
        self.assertFalse(result["available"])
        self.assertIsNone(result["checkedAt"])
        self.assertEqual(len(self.calls), 1)

    async def test_recovery_after_failure(self):
        self.replies.append(httpx.Response(503))
        await self.feed.snapshot()
        self.feed.next_check = 0
        result = await self.first_sync()
        self.assertTrue(result["available"])
        self.assertFalse(result["stale"])


class RouteTests(unittest.TestCase):
    def test_status_codes_and_no_store(self):
        app = FastAPI()
        app.include_router(vocab.router)
        with TestClient(app) as client:
            for available, status in ((True, 200), (False, 503)):
                with patch.object(vocab.feed, "snapshot", return_value={"available": available, "words": []}):
                    response = client.get("/api/v1/vocabulary")
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.headers["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
