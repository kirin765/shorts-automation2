from __future__ import annotations

import unittest
from unittest import mock

from shorts.providers import _decode_output_json, _responses_request_json


class TestProvidersJson(unittest.TestCase):
    def test_decode_output_json_accepts_code_fence(self) -> None:
        data = {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": "```json\n{\"evaluations\": []}\n```",
                        }
                    ]
                }
            ]
        }

        obj = _decode_output_json(data)

        self.assertEqual(obj, {"evaluations": []})

    def test_responses_request_json_retries_after_malformed_json(self) -> None:
        payload = {
            "input": [{"role": "system", "content": "return json"}],
            "max_output_tokens": 700,
        }
        first = {
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": "{\"evaluations\":[{\"candidate_id\":\"c1\",\"selection_reason\":\"ok\"",
                        }
                    ]
                }
            ],
        }
        second = {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": "{\"evaluations\":[]}",
                        }
                    ]
                }
            ]
        }

        with mock.patch("shorts.providers._responses_request", side_effect=[first, second]) as request_call:
            obj = _responses_request_json(mock.Mock(), "key", payload, max_attempts=2)

        self.assertEqual(obj, {"evaluations": []})
        self.assertEqual(request_call.call_count, 2)
        second_payload = request_call.call_args_list[1].args[2]
        self.assertEqual(second_payload["max_output_tokens"], 1400)
        self.assertEqual(second_payload["input"][-1]["role"], "system")

