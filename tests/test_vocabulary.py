import asyncio
import json
import unittest
from unittest.mock import patch, MagicMock

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


class AddWordRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(vocab.router)
        self.fake_user = MagicMock(id=42, username="tester")
        self.app.dependency_overrides[vocab.get_current_user] = lambda: self.fake_user
        # 限流不影响单测断言
        self._limit_patch = patch.object(vocab.vocab_write_limiter, "limit")
        self._limit_patch.start()
        self.addCleanup(self._limit_patch.stop)

    def client(self):
        return TestClient(self.app)

    def test_add_requires_login(self):
        app = FastAPI()
        app.include_router(vocab.router)
        with TestClient(app) as c:
            r = c.post("/api/v1/vocabulary", json={"word": "x"})
        self.assertEqual(r.status_code, 401)

    def test_add_success(self):
        async def fake_read(rel):
            return {"content": json.dumps({"words": []}), "sha": "a"}
        written = {}
        async def fake_write(rel, text, message, sha=None):
            written.update(rel=rel, text=text, message=message, sha=sha)
            return {"sha": "b", "commit_url": "http://commit/1"}
        async def fake_apply(words):
            written["applied"] = words
        with self.client() as c:
            with patch.object(vocab.content_store, "read_text", side_effect=fake_read), \
                 patch.object(vocab.content_store, "write_text", side_effect=fake_write), \
                 patch.object(vocab.feed, "apply_words", side_effect=fake_apply):
                r = c.post("/api/v1/vocabulary",
                           json={"word": " resilient ", "phonetic": " /r/ ", "zh": " 有韧性的 "})
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual(body["word"], "resilient")
        self.assertEqual(body["phonetic"], "/r/")
        self.assertEqual(body["zh"], "有韧性的")
        self.assertIsInstance(body["createdAt"], int)
        self.assertEqual(body["commit_url"], "http://commit/1")
        self.assertEqual(written["sha"], "a")
        self.assertIn("resilient", written["text"])
        self.assertEqual(written["applied"][0]["word"], "resilient")

    def test_duplicate_is_case_insensitive_and_not_written(self):
        async def fake_read(rel):
            return {"content": json.dumps({"words": [{"word": "resilient"}]}), "sha": "a"}
        with self.client() as c:
            with patch.object(vocab.content_store, "read_text", side_effect=fake_read), \
                 patch.object(vocab.content_store, "write_text") as wt:
                r = c.post("/api/v1/vocabulary", json={"word": " Resilient "})
        self.assertEqual(r.status_code, 409)
        wt.assert_not_called()

    def test_blank_word_is_rejected(self):
        with self.client() as c:
            r = c.post("/api/v1/vocabulary", json={"word": "   "})
        self.assertEqual(r.status_code, 422)

    def test_content_store_error_is_mapped(self):
        from content_store import ContentError
        async def fake_read(rel):
            raise ContentError("当前为只读，无法保存", 409)
        with self.client() as c:
            with patch.object(vocab.content_store, "read_text", side_effect=fake_read):
                r = c.post("/api/v1/vocabulary", json={"word": "x"})
        self.assertEqual(r.status_code, 409)

    def test_corrupt_remote_file_is_500(self):
        async def fake_read(rel):
            return {"content": "not json", "sha": "a"}
        with self.client() as c:
            with patch.object(vocab.content_store, "read_text", side_effect=fake_read):
                r = c.post("/api/v1/vocabulary", json={"word": "x"})
        self.assertEqual(r.status_code, 500)


class DeleteWordRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(vocab.router)
        self.fake_user = MagicMock(id=42, username="tester")
        self.app.dependency_overrides[vocab.get_current_user] = lambda: self.fake_user
        self._limit_patch = patch.object(vocab.vocab_write_limiter, "limit")
        self._limit_patch.start()
        self.addCleanup(self._limit_patch.stop)

    def client(self):
        return TestClient(self.app)

    def test_delete_requires_login(self):
        app = FastAPI()
        app.include_router(vocab.router)
        with TestClient(app) as c:
            r = c.request("DELETE", "/api/v1/vocabulary", json={"word": "x"})
        self.assertEqual(r.status_code, 401)

    def test_delete_removes_word_and_keeps_az_order(self):
        async def fake_read(rel):
            return {"content": json.dumps({"words": [
                {"word": "resilient", "zh": "有韧性的"},
                {"word": "abandon", "zh": "放弃"},
                {"word": "zebra", "zh": "斑马"},
            ]}), "sha": "a"}
        written = {}
        async def fake_write(rel, text, message, sha=None):
            written.update(text=text, message=message, sha=sha)
            return {"sha": "b", "commit_url": "http://commit/2"}
        async def fake_apply(words):
            written["applied"] = words
        with self.client() as c:
            with patch.object(vocab.content_store, "read_text", side_effect=fake_read), \
                 patch.object(vocab.content_store, "write_text", side_effect=fake_write), \
                 patch.object(vocab.feed, "apply_words", side_effect=fake_apply):
                r = c.request("DELETE", "/api/v1/vocabulary", json={"word": "  Resilient  "})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["deleted"])
        self.assertEqual(r.json()["word"], "resilient")
        remaining = [w["word"] for w in json.loads(written["text"])["words"]]
        self.assertEqual(remaining, ["abandon", "zebra"])
        self.assertEqual([w["word"] for w in written["applied"]], ["abandon", "zebra"])
        self.assertIn("删除单词 resilient", written["message"])
        self.assertEqual(written["sha"], "a")

    def test_delete_missing_word_is_404_and_not_written(self):
        async def fake_read(rel):
            return {"content": json.dumps({"words": [{"word": "abandon"}]}), "sha": "a"}
        with self.client() as c:
            with patch.object(vocab.content_store, "read_text", side_effect=fake_read), \
                 patch.object(vocab.content_store, "write_text") as wt:
                r = c.request("DELETE", "/api/v1/vocabulary", json={"word": "nothing"})
        self.assertEqual(r.status_code, 404)
        self.assertIn("不在记录中", r.json()["detail"])
        wt.assert_not_called()

    def test_delete_content_store_error_is_mapped(self):
        from content_store import ContentError
        async def fake_read(rel):
            raise ContentError("当前为只读，无法保存", 409)
        with self.client() as c:
            with patch.object(vocab.content_store, "read_text", side_effect=fake_read):
                r = c.request("DELETE", "/api/v1/vocabulary", json={"word": "x"})
        self.assertEqual(r.status_code, 409)


class LookupRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(vocab.router)
        self._limit_patch = patch.object(vocab.vocab_lookup_limiter, "limit")
        self._limit_patch.start()
        self.addCleanup(self._limit_patch.stop)
        vocab.LOOKUP_CACHE.clear()

    def test_blank_and_non_english_words_are_rejected(self):
        with TestClient(self.app) as c:
            self.assertEqual(c.get("/api/v1/vocabulary/lookup?word=").status_code, 422)
            self.assertEqual(c.get("/api/v1/vocabulary/lookup?word=%E5%8D%95%E8%AF%8D").status_code, 422)
            self.assertEqual(c.get("/api/v1/vocabulary/lookup?word=a1!").status_code, 422)

    async def test_lookup_returns_phonetic_and_chinese(self):
        async def fake_iciba(word, client):
            return "adj. 有韧性的"
        async def fake_phonetic(word, client):
            return "/rɪˈzɪliənt/"
        with patch.object(vocab, "_iciba_zh", side_effect=fake_iciba), \
             patch.object(vocab, "_phonetic_from_dictionary_api", side_effect=fake_phonetic), \
             TestClient(self.app) as c:
            r = c.get("/api/v1/vocabulary/lookup?word=resilient")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["phonetic"], "/rɪˈzɪliənt/")
        self.assertEqual(body["zh"], "adj. 有韧性的")
        self.assertIn("iciba", body["sources"])

    async def test_lookup_survives_upstream_failures(self):
        async def boom(word, client):
            raise RuntimeError("offline")
        with patch.object(vocab, "_iciba_zh", side_effect=boom), \
             patch.object(vocab, "_phonetic_from_dictionary_api", side_effect=boom), \
             patch.object(vocab, "_phonetic_from_wiktionary", side_effect=boom), \
             TestClient(self.app) as c:
            r = c.get("/api/v1/vocabulary/lookup?word=resilient")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["phonetic"], "")
        self.assertEqual(r.json()["zh"], "")

    def test_result_is_cached(self):
        async def fake_iciba(word, client):
            fake_iciba.calls += 1
            return "n. 斑马"
        fake_iciba.calls = 0
        async def fake_phonetic(word, client):
            return "/ˈzebrə/"
        with patch.object(vocab, "_iciba_zh", side_effect=fake_iciba), \
             patch.object(vocab, "_phonetic_from_dictionary_api", side_effect=fake_phonetic), \
             TestClient(self.app) as c:
            c.get("/api/v1/vocabulary/lookup?word=zebra")
            second = c.get("/api/v1/vocabulary/lookup?word=Zebra")
        self.assertEqual(fake_iciba.calls, 1)
        self.assertTrue(second.json()["cached"])


class UpstreamParserTests(unittest.IsolatedAsyncioTestCase):
    """外部字典接口的结构解析（不联网，用样例响应）。"""
    class FakeResponse:
        def __init__(self, status_code=200, text="", payload=None):
            self.status_code = status_code
            self.text = text
            self._payload = payload

        def json(self):
            if self._payload is None:
                raise ValueError("not json")
            return self._payload

    class FakeClient:
        def __init__(self, response):
            self.response = response
            self.calls = []

        async def get(self, url, **kw):
            self.calls.append((url, kw))
            return self.response

    async def test_bing_phonetic_prefers_us(self):
        html = ('<div class="hd_prUS b_primtxt">美&#160;[ˌfoʊtoʊˈsɪnθəsɪs] </div>'
                '<div class="hd_pr b_primtxt">英国&#160;[ˌfəʊtəʊˈsɪnθəsɪs] </div>')
        client = self.FakeClient(self.FakeResponse(200, html))
        self.assertEqual(await vocab._phonetic_from_bing("photosynthesis", client),
                         "/ˌfoʊtoʊˈsɪnθəsɪs/")

    async def test_bing_phonetic_ignores_scripts(self):
        """页面里的 JS 也会出现方括号，不能被当成音标。"""
        html = 'var x=hd_pr["use strict"];function(){return [CDATA[alert(1)]'
        client = self.FakeClient(self.FakeResponse(200, html))
        self.assertEqual(await vocab._phonetic_from_bing("photosynthesis", client), "")

    async def test_youdao_fallback_meaning(self):
        payload = {"data": {"entries": [{"explain": "n. 光合作用", "entry": "photosynthesis"}]}}
        client = self.FakeClient(self.FakeResponse(200, payload=payload))
        self.assertEqual(await vocab._zh_from_youdao("photosynthesis", client), "n. 光合作用")

    async def test_upstream_http_error_is_empty(self):
        client = self.FakeClient(self.FakeResponse(500, "boom"))
        self.assertEqual(await vocab._phonetic_from_bing("x", client), "")
        self.assertEqual(await vocab._zh_from_youdao("x", client), "")

    async def test_iciba_picks_exact_match_and_keeps_pos(self):
        payload = {"message": [
            {"key": "resiliently", "means": [{"part": "adv.", "means": ["有恢复力地"]}]},
            {"key": "resilient", "means": [{"part": "adj.", "means": ["能复原的", "弹回的"]}]},
        ]}
        client = self.FakeClient(self.FakeResponse(200, payload=payload))
        self.assertEqual(await vocab._iciba_zh("resilient", client), "adj. 能复原的；弹回的")

    def test_cmudict_parsing_skips_comments_and_variants(self):
        text = ";;; comment\nRESILIENT  R IH0 Z IH1 L Y AH0 N T\nRESILIENT(1)  R IH0 Z IH2 L Y AH0 N T\nZEBRA  Z IY1 B R AH0\n"
        table = vocab._parse_cmudict(text)
        self.assertEqual(table["resilient"], ["R", "IH0", "Z", "IH1", "L", "Y", "AH0", "N", "T"])
        self.assertEqual(table["zebra"], ["Z", "IY1", "B", "R", "AH0"])
        self.assertNotIn("resilient(1)", table)

    def test_arpabet_to_ipa_stress_goes_before_syllable_onset(self):
        self.assertEqual(vocab._arpabet_to_ipa(
            ["R", "IH0", "Z", "IH1", "L", "Y", "AH0", "N", "T"]), "rɪˈzɪljənt")
        self.assertEqual(vocab._arpabet_to_ipa(
            ["F", "OW2", "T", "OW0", "S", "IH1", "N", "TH", "AH0", "S", "IH2", "S"]),
            "ˌfoʊtoʊˈsɪnθəsɪs")
        self.assertEqual(vocab._arpabet_to_ipa(["Z", "IY1", "B", "R", "AH0"]), "ˈziːbrə")
        self.assertEqual(vocab._arpabet_to_ipa([]), "")

    async def test_wiktionary_ipa_normalizes_r(self):
        client = self.FakeClient(self.FakeResponse(200, "{{IPA|en|/ɹɪˈzɪl.jənt/|/ɹɪˈzɪli.ənt/}}"))
        self.assertEqual(await vocab._phonetic_from_wiktionary("resilient", client),
                         "/rɪˈzɪl.jənt/")


class AutoFillAddTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(vocab.router)
        self.fake_user = MagicMock(id=7, username="tester")
        self.app.dependency_overrides[vocab.get_current_user] = lambda: self.fake_user
        self._limit_patch = patch.object(vocab.vocab_write_limiter, "limit")
        self._limit_patch.start()
        self.addCleanup(self._limit_patch.stop)
        vocab.LOOKUP_CACHE.clear()

    def add(self, body, lookup_result):
        async def fake_read(rel):
            return {"content": json.dumps({"words": []}), "sha": "a"}
        async def fake_write(rel, text, message, sha=None):
            return {"sha": "b", "commit_url": "http://commit/1", "text": text}
        async def fake_lookup(word):
            return lookup_result
        async def fake_apply(words):
            return None
        with TestClient(self.app) as c:
            with patch.object(vocab.content_store, "read_text", side_effect=fake_read), \
                 patch.object(vocab.content_store, "write_text", side_effect=fake_write), \
                 patch.object(vocab.feed, "apply_words", side_effect=fake_apply), \
                 patch.object(vocab, "lookup_word_info", side_effect=fake_lookup) as mocked:
                r = c.post("/api/v1/vocabulary", json=body)
                return r, mocked

    def test_only_word_is_enough(self):
        r, mocked = self.add({"word": "zebra"}, {"phonetic": "/ˈzebrə/", "zh": "n. 斑马"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["phonetic"], "/ˈzebrə/")
        self.assertEqual(r.json()["zh"], "n. 斑马")
        mocked.assert_called_once()

    def test_manual_values_win(self):
        r, mocked = self.add({"word": "zebra", "phonetic": "/z/", "zh": "自定义"},
                             {"phonetic": "/ˈzebrə/", "zh": "n. 斑马"})
        self.assertEqual(r.json()["phonetic"], "/z/")
        self.assertEqual(r.json()["zh"], "自定义")
        mocked.assert_not_called()

    def test_lookup_failure_does_not_block_saving(self):
        async def boom(word):
            raise RuntimeError("offline")
        async def fake_read(rel):
            return {"content": json.dumps({"words": []}), "sha": "a"}
        async def fake_write(rel, text, message, sha=None):
            return {"sha": "b"}
        with TestClient(self.app) as c:
            with patch.object(vocab.content_store, "read_text", side_effect=fake_read), \
                 patch.object(vocab.content_store, "write_text", side_effect=fake_write), \
                 patch.object(vocab.feed, "apply_words"), \
                 patch.object(vocab, "lookup_word_info", side_effect=boom):
                r = c.post("/api/v1/vocabulary", json={"word": "zzzz"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["phonetic"], "")


class ExportRouteTests(unittest.TestCase):
    WORDS = [{"word": "zebra", "phonetic": "/ˈzebrə/", "zh": "斑马"},
             {"word": "abandon", "phonetic": "/əˈbændən/", "zh": "放弃"},
             {"word": "resilient", "phonetic": "/rɪˈzɪliənt/", "zh": "有韧性的"}]

    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(vocab.router)

    def fetch(self, query="", words=None, available=True):
        snapshot = {"available": available, "words": self.WORDS if words is None else words}
        with TestClient(self.app) as c:
            with patch.object(vocab.feed, "snapshot", return_value=snapshot):
                return c.get("/api/v1/vocabulary/export" + query)

    def read_docx(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertIn("wordprocessingml.document", response.headers["content-type"])
        self.assertIn("attachment", response.headers["content-disposition"])
        import io, zipfile
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertIn("word/document.xml", archive.namelist())
            return archive.read("word/document.xml").decode("utf-8")

    def test_export_is_a_docx_with_two_columns(self):
        xml = self.read_docx(self.fetch())
        self.assertIn("英文", xml)
        self.assertIn("中文", xml)
        for text in ("abandon", "resilient", "zebra", "有韧性的", "斑马"):
            self.assertIn(text, xml)

    def test_export_defaults_to_az_order(self):
        xml = self.read_docx(self.fetch())
        order = [xml.find(text) for text in ("abandon", "resilient", "zebra")]
        self.assertEqual(order, sorted(order))

    def test_export_reverse_and_filter_and_no_phonetic(self):
        xml = self.read_docx(self.fetch("?sort=za"))
        order = [xml.find(text) for text in ("abandon", "resilient", "zebra")]
        self.assertEqual(order, sorted(order, reverse=True))
        filtered = self.read_docx(self.fetch("?q=%E6%96%91%E9%A9%AC"))   # 斑马
        self.assertIn("zebra", filtered)
        self.assertNotIn("abandon", filtered)
        plain = self.read_docx(self.fetch("?phonetic=false"))
        self.assertNotIn("/rɪˈzɪliənt/", plain)
        self.assertIn("resilient", plain)

    def test_export_unavailable_is_503(self):
        self.assertEqual(self.fetch(available=False).status_code, 503)

    def test_export_empty_list_still_works(self):
        xml = self.read_docx(self.fetch(words=[]))
        self.assertIn("没有可导出的单词", xml)


if __name__ == "__main__":
    unittest.main()
