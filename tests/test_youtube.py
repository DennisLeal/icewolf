import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from icewolf import youtube
from icewolf.desktop import AssistantWorker, IcewolfWindow


def video(video_id, title, age=""):
    return {"videoRenderer": {"videoId": video_id, "title": {"runs": [{"text": title}]},
                              "ownerText": {"simpleText": "Channel"},
                              "publishedTimeText": {"simpleText": age}}}


class YouTubeTests(unittest.TestCase):
    def test_extracts_natural_requests(self):
        examples = (
            ("search clasical musical piano and play it for me please", "clasical musical piano", False),
            ("search recent video about tenz the valorant superstar and have him popup a window for me to make me watch it",
             "tenz the valorant superstar", True),
            ("Hey Icewolf, play piano music on YouTube please", "piano music", False),
            ("Find videos about cats on YouTube", "cats", False),
        )
        for text, query, recent in examples:
            with self.subTest(text=text):
                self.assertEqual(youtube.extract_request(text), youtube.VideoRequest(query, recent))
        for text in ("Search my emails", "Do not play music", "Tell me about YouTube",
                     "Show project links"):
            self.assertIsNone(youtube.extract_request(text))

    def service(self, data, status=200):
        conn = MagicMock()
        response = conn.getresponse.return_value
        response.status = status
        response.read.return_value = ("var ytInitialData = " + json.dumps(data) + ";").encode()
        return conn

    def test_search_selects_valid_organic_result(self):
        conn = self.service({"results": [video("invalid", "invalid"),
                                         video("abcdefghijk", "Song")]})
        with patch("icewolf.youtube.http.client.HTTPSConnection", return_value=conn):
            result = youtube.search_first(youtube.VideoRequest("piano & cello"))
        self.assertEqual(result.url, "https://www.youtube.com/watch?v=abcdefghijk")
        query = parse_qs(urlsplit(conn.request.call_args.args[1]).query)
        self.assertEqual(query["search_query"], ["piano & cello"])
        conn.close.assert_called_once()

    def test_recent_selects_newest_dated_result_even_when_sort_is_ignored(self):
        conn = self.service({"results": [video("aaaaaaaaaaa", "Old", "2y ago"),
                                         video("bbbbbbbbbbb", "New", "3mo ago"),
                                         video("ccccccccccc", "Unknown")]})
        with patch("icewolf.youtube.http.client.HTTPSConnection", return_value=conn):
            result = youtube.search_first(youtube.VideoRequest("news", True))
        self.assertEqual(result.title, "New")
        self.assertEqual(parse_qs(urlsplit(conn.request.call_args.args[1]).query)["sp"], ["CAI="])

    def test_search_errors_are_explicit(self):
        with self.assertRaisesRegex(ValueError, "Tell me"):
            youtube.search_first(youtube.VideoRequest(""))
        conn = self.service({"results": []})
        with patch("icewolf.youtube.http.client.HTTPSConnection", return_value=conn):
            with self.assertRaisesRegex(RuntimeError, "No matching"):
                youtube.search_first(youtube.VideoRequest("test"))
            with self.assertRaisesRegex(RuntimeError, "dated"):
                youtube.search_first(youtube.VideoRequest("test", True))
        conn.getresponse.return_value.status = 403
        with patch("icewolf.youtube.http.client.HTTPSConnection", return_value=conn):
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                youtube.search_first(youtube.VideoRequest("test"))
        conn.request.side_effect = OSError("network")
        with patch("icewolf.youtube.http.client.HTTPSConnection", return_value=conn):
            with self.assertRaisesRegex(RuntimeError, "internet connection"):
                youtube.search_first(youtube.VideoRequest("test"))

    def test_invalid_page_and_oversized_response(self):
        conn = self.service({})
        with patch("icewolf.youtube.http.client.HTTPSConnection", return_value=conn):
            conn.getresponse.return_value.read.return_value = b"consent page"
            with self.assertRaisesRegex(RuntimeError, "searchable results"):
                youtube.search_first(youtube.VideoRequest("test"))
            conn.getresponse.return_value.read.return_value = b"x" * (youtube.MAX_RESPONSE_BYTES + 1)
            with self.assertRaisesRegex(RuntimeError, "large page"):
                youtube.search_first(youtube.VideoRequest("test"))

    def test_worker_routes_request_and_respects_cancellation(self):
        client, speaker = MagicMock(), MagicMock()
        worker = AssistantWorker(client, "text", "")
        requested = []
        worker.youtube_requested.connect(lambda url, title: requested.append((url, title)))
        result = youtube.Video("abcdefghijk", "Piano", "Channel")
        with patch("icewolf.desktop.youtube.search_first", return_value=result) as search:
            worker.respond("search piano and play it", speaker)
        search.assert_called_once_with(youtube.VideoRequest("piano"))
        self.assertEqual(requested, [(result.url, "Piano")])
        client.reply.assert_not_called()
        worker = AssistantWorker(client, "text", "")
        requested = []
        worker.youtube_requested.connect(lambda *args: requested.append(args))
        speaker.say.side_effect = lambda *args, **kwargs: worker.stop()
        with patch("icewolf.desktop.youtube.search_first", return_value=result):
            worker.respond("play piano", speaker)
        self.assertEqual(requested, [])

    def test_typed_video_request_does_not_require_local_llm(self):
        client = MagicMock()
        speaker = MagicMock()
        client.check_model.side_effect = RuntimeError("model unavailable")
        worker = AssistantWorker(client, "text", "", "play piano", language="Tagalog")
        requests, errors = [], []
        worker.youtube_requested.connect(lambda *args: requests.append(args))
        worker.failed.connect(errors.append)
        with patch("icewolf.desktop.create_speaker", return_value=speaker), \
             patch("icewolf.desktop.youtube.search_first",
                   return_value=youtube.Video("abcdefghijk", "Piano", "Channel")):
            worker.run()
        self.assertEqual(requests, [("https://www.youtube.com/watch?v=abcdefghijk", "Piano")])
        self.assertEqual(errors, [])
        client.check_model.assert_not_called()
        client.reply.assert_not_called()

    def test_browser_failure_is_reported(self):
        window = MagicMock()
        with patch("icewolf.desktop.webbrowser.open_new", return_value=False):
            IcewolfWindow.open_youtube_video(window, "https://www.youtube.com/watch?v=abcdefghijk", "Piano")
        window.show_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
