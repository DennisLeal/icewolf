import base64
import json
import unittest
from unittest.mock import MagicMock, patch

from icewolf.github_repo import (
    MAX_README_CHARS, MAX_RESPONSE_BYTES, RepositoryOverview, _get_json,
    extract_repository_request, fetch_overview, parse_repository_url,
)
from icewolf.ollama import OllamaClient


class GithubRepoTests(unittest.TestCase):
    def test_strict_repository_urls(self):
        self.assertEqual(parse_repository_url("https://github.com/owner/my-repo.git"),
                         ("owner", "my-repo"))
        for value in (
            "http://github.com/owner/repo", "https://github.com@evil.example/owner/repo",
            "https://github.com:443/owner/repo", "https://github.com/owner/repo/tree/main",
            "https://github.com/owner/repo?token=secret", "https://github.com/owner/..",
            "https://github.com/owner/repo#section", "https://github.com/owner",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_repository_url(value)

    def test_extracts_conversation_link_and_question(self):
        url, question = extract_repository_request(
            "What is this project? https://github.com/owner/repo"
        )
        self.assertEqual(url, "https://github.com/owner/repo")
        self.assertEqual(question, "What is this project?")
        self.assertEqual(extract_repository_request("https://github.com/owner/repo.")[1],
                         "Summarize this repository.")
        self.assertIsNone(extract_repository_request("Check my GitHub repository"))
        with self.assertRaises(ValueError):
            extract_repository_request("https://github.com/a/b https://github.com/c/d")
        with self.assertRaises(ValueError):
            extract_repository_request("https://github.com.evil.example/a/b")

    def test_public_metadata_and_readme_are_bounded(self):
        long_text = "A" * (MAX_README_CHARS + 10)
        with patch("icewolf.github_repo._get_json", side_effect=[
            {"private": False, "description": "A project", "language": "Python"},
            {"encoding": "base64", "content": base64.b64encode(long_text.encode()).decode()},
        ]) as get:
            result = fetch_overview("https://github.com/owner/repo")
        self.assertEqual(len(result.readme), MAX_README_CHARS)
        self.assertTrue(result.readme_truncated)
        self.assertEqual([call.args[0] for call in get.call_args_list],
                         ["/repos/owner/repo", "/repos/owner/repo/readme"])

    def test_missing_readme_and_private_repository(self):
        with patch("icewolf.github_repo._get_json", side_effect=[{"private": False}, None]):
            self.assertEqual(fetch_overview("https://github.com/a/b").readme, "")
        for metadata in (None, {"private": True}, {}):
            with self.subTest(metadata=metadata), \
                 patch("icewolf.github_repo._get_json", return_value=metadata), \
                 self.assertRaises(RuntimeError):
                fetch_overview("https://github.com/a/b")

    def test_bad_readme_and_rate_limit_are_errors(self):
        with patch("icewolf.github_repo._get_json", side_effect=[
            {"private": False}, {"encoding": "base64", "content": "!!!"}
        ]), self.assertRaisesRegex(RuntimeError, "decoded"):
            fetch_overview("https://github.com/a/b")
        conn = MagicMock()
        conn.getresponse.return_value.status = 403
        with patch("icewolf.github_repo.http.client.HTTPSConnection", return_value=conn), \
             self.assertRaisesRegex(RuntimeError, "403"):
            _get_json("/repos/a/b")
        conn.close.assert_called_once()

    def test_connection_is_fixed_https_host_and_no_redirects(self):
        conn = MagicMock()
        response = conn.getresponse.return_value
        response.status = 200
        response.read.return_value = json.dumps({"private": False}).encode()
        with patch("icewolf.github_repo.http.client.HTTPSConnection", return_value=conn) as factory:
            self.assertEqual(_get_json("/repos/a/b"), {"private": False})
        factory.assert_called_once_with("api.github.com", timeout=15)
        conn.request.assert_called_once()
        response.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)
        response.status = 302
        with patch("icewolf.github_repo.http.client.HTTPSConnection", return_value=conn), \
             self.assertRaisesRegex(RuntimeError, "302"):
            _get_json("/repos/a/b")

    def test_ollama_receives_untrusted_excerpt_not_global_history(self):
        client = OllamaClient("local")
        overview = RepositoryOverview("https://github.com/a/b", "Example", "Python", "Text", False)
        with patch.object(client, "_post", return_value={"message": {"content": "Overview"}}) as post:
            self.assertEqual(client.repository_reply(overview, "What is it?"), "Overview")
        messages = post.call_args.args[1]["messages"]
        self.assertIn("untrusted", messages[0]["content"])
        self.assertIn("README excerpt", messages[1]["content"])
        self.assertEqual(len(client.messages), 1)


if __name__ == "__main__":
    unittest.main()
