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
                        _openai_response(["new-topic-a", "new-topic-b", "new-topic-c"]),
                    ],
                ) as post_mock,
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
            self.assertEqual(produced, ["new-topic-a", "new-topic-b"])
            history = [line.strip() for line in hist_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(history, ["dup-topic", "new-topic-a", "new-topic-b"])

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
                        _openai_response(["dup-topic", "dup-topic"]),
                        _openai_response(["dup-topic", "dup-topic"]),
                    ],
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
                    return_value=_openai_response(["dup-topic-a", "dup-topic-b", "dup-topic-c"]),
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


if __name__ == "__main__":
    unittest.main()
