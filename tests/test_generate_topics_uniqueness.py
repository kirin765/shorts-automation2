import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _load_generate_topics_module():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "generate_topics.py"
    spec = importlib.util.spec_from_file_location("generate_topics_module", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load scripts/generate_topics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _openai_response(topics: list[str]):
    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({"topics": topics}, ensure_ascii=False),
                            }
                        ]
                    }
                ]
            }

    return _Resp()


class _FakeGetResponse:
    def __init__(self, text: str = "<rss><channel></channel></rss>", items: list[dict] | None = None):
        self._text = text
        self._items = items or []

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"items": self._items}

    @property
    def text(self) -> str:
        return self._text


class TestGenerateTopicsUniqueness(unittest.TestCase):
    def test_strict_mode_refills_until_count(self) -> None:
        generate_topics = _load_generate_topics_module()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_path = root / "topics.txt"
            hist_path = root / "topics_history.txt"
            hist_path.write_text("dup-topic\n", encoding="utf-8")

            cfg = {"openai_api_key": "test-key", "openai_base_url": "https://api.openai.com/v1"}
            with (
                patch.object(generate_topics, "load_config", return_value=cfg),
                patch.object(
                    generate_topics.requests,
                    "post",
                    side_effect=[
                        _openai_response(["dup-topic", "dup-topic", "dup-topic"]),
                        _openai_response(["왜 AI가 느려지는지? 3가지 이유", "쇼츠 시작 3초로 끌리는 이유", "실수 하나가 시청율을 떨어뜨리는 순간"]),
                    ],
                ) as post_mock,
                patch.object(
                    generate_topics.requests,
                    "get",
                    return_value=_FakeGetResponse(),
                ),
                patch.object(
                    generate_topics,
                    "_is_high_interest_topic",
                    return_value=True,
                ),
                patch.object(
                    sys,
                    "argv",
                    [
                        "generate_topics.py",
                        "--config",
                        "ENV",
                        "--out",
                        str(out_path),
                        "--history",
                        str(hist_path),
                        "--count",
                        "2",
                        "--uniqueness-mode",
                        "strict",
                        "--max-attempts",
                        "2",
                    ],
                ),
            ):
                rc = generate_topics.main()

            self.assertEqual(rc, 0)
            self.assertEqual(post_mock.call_count, 2)
            produced = [line.strip() for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(produced), 2)
            self.assertEqual(produced, ["왜 AI가 느려지는지? 3가지 이유", "쇼츠 시작 3초로 끌리는 이유"])
            history = [line.strip() for line in hist_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(history, ["dup-topic", "왜 AI가 느려지는지? 3가지 이유", "쇼츠 시작 3초로 끌리는 이유"])

    def test_strict_mode_failure_does_not_mutate_history(self) -> None:
        generate_topics = _load_generate_topics_module()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_path = root / "topics.txt"
            hist_path = root / "topics_history.txt"
            hist_path.write_text("dup-topic\n", encoding="utf-8")
            before = hist_path.read_text(encoding="utf-8")

            cfg = {"openai_api_key": "test-key", "openai_base_url": "https://api.openai.com/v1"}
            with (
                patch.object(generate_topics, "load_config", return_value=cfg),
                patch.object(
                    generate_topics.requests,
                    "post",
                    side_effect=[
                        _openai_response(["dup-topic", "딥러닝 토픽 1", "딥러닝 토픽 1"]),
                        _openai_response(["dup-topic", "딥러닝 토픽 1", "딥러닝 토픽 1"]),
                    ],
                ),
                patch.object(
                    generate_topics.requests,
                    "get",
                    return_value=_FakeGetResponse(),
                ),
                patch.object(generate_topics, "_is_high_interest_topic", return_value=True),
                patch.object(
                    sys,
                    "argv",
                    [
                        "generate_topics.py",
                        "--config",
                        "ENV",
                        "--out",
                        str(out_path),
                        "--history",
                        str(hist_path),
                        "--count",
                        "2",
                        "--uniqueness-mode",
                        "strict",
                        "--max-attempts",
                        "2",
                    ],
                ),
            ):
                with self.assertRaises(SystemExit) as cm:
                    generate_topics.main()

            self.assertIn("failed to provide unique set", str(cm.exception))
            self.assertFalse(out_path.exists())
            self.assertEqual(hist_path.read_text(encoding="utf-8"), before)

    def test_best_effort_mode_keeps_legacy_relaxed_behavior(self) -> None:
        generate_topics = _load_generate_topics_module()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_path = root / "topics.txt"
            hist_path = root / "topics_history.txt"
            hist_path.write_text("dup-topic-a\ndup-topic-b\n", encoding="utf-8")

            cfg = {"openai_api_key": "test-key", "openai_base_url": "https://api.openai.com/v1"}
            with (
                patch.object(generate_topics, "load_config", return_value=cfg),
                patch.object(
                    generate_topics.requests,
                    "post",
                    return_value=_openai_response(
                        ["dup-topic-a", "숏스 제목 3단계 체크리스트", "왜 쇼츠가 금방 식힐까: 4가지 이유"]
                    ),
                ),
                patch.object(
                    generate_topics.requests,
                    "get",
                    return_value=_FakeGetResponse(),
                ),
                patch.object(generate_topics, "_is_high_interest_topic", return_value=True),
                patch.object(
                    sys,
                    "argv",
                    [
                        "generate_topics.py",
                        "--config",
                        "ENV",
                        "--out",
                        str(out_path),
                        "--history",
                        str(hist_path),
                        "--count",
                        "2",
                        "--uniqueness-mode",
                        "best_effort",
                        "--max-attempts",
                        "1",
                    ],
                ),
            ):
                rc = generate_topics.main()

            self.assertEqual(rc, 0)
            produced = [line.strip() for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(produced), 2)

    def test_request_topics_once_includes_engagement_guidance(self) -> None:
        generate_topics = _load_generate_topics_module()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_path = root / "topics.txt"
            hist_path = root / "topics_history.txt"
            captured: dict[str, object] = {}

            cfg = {"openai_api_key": "test-key", "openai_base_url": "https://api.openai.com/v1"}

            def fake_post(url: str, headers: dict[str, str], json: dict, timeout: int):
                captured["json"] = json
                return _openai_response(["왜 AI가 느려지는지? 3가지 이유", "쇼츠는 첫 3초가 전부다"])

            with (
                patch.object(generate_topics, "load_config", return_value=cfg),
                patch.object(generate_topics.requests, "post", side_effect=fake_post),
                patch.object(generate_topics.requests, "get", return_value=_FakeGetResponse()),
                patch.object(generate_topics, "_is_high_interest_topic", return_value=True),
                patch.object(
                    sys,
                    "argv",
                    [
                        "generate_topics.py",
                        "--config",
                        "ENV",
                        "--out",
                        str(out_path),
                        "--history",
                        str(hist_path),
                        "--count",
                        "2",
                        "--uniqueness-mode",
                        "strict",
                        "--max-attempts",
                        "1",
                    ],
                ),
            ):
                generate_topics.main()

            payload_inputs = captured["json"]["input"]  # type: ignore[index]
            system_msg = next(item["content"] for item in payload_inputs if item["role"] == "system")
            user_msg = next(item["content"] for item in payload_inputs if item["role"] == "user")

            self.assertIn("high-retention", system_msg)
            self.assertIn("Prioritize strong hooks", user_msg)
            self.assertIn("concrete situations", user_msg)


if __name__ == "__main__":
    unittest.main()
