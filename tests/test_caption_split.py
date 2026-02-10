import unittest

import run_short


class TestCaptionSplitDense(unittest.TestCase):
    def test_dense_split_splits_on_connectors(self) -> None:
        text = "이건 중요한 포인트예요. 그래서 결론은 간단합니다. 하지만 한 줄이 너무 길면 읽기 힘들어요."
        out = run_short.split_for_captions_dense(text, max_chars=14)
        self.assertTrue(out)
        # Connector tokens should appear as their own leading chunk at least once.
        self.assertTrue(any(s.startswith("그래서") for s in out))
        self.assertTrue(any(s.startswith("하지만") for s in out))

    def test_dense_split_keeps_lines_short(self) -> None:
        text = "자막은 모바일에서 읽기 쉬워야 합니다. 그래서 길면 끊고, 쉼표나 구두점에서 더 자주 나눕니다."
        max_chars = 18
        out = run_short.split_for_captions_dense(text, max_chars=max_chars)
        self.assertTrue(out)
        # textwrap.wrap(break_long_words=False) can produce an overlong token if a single "word" is too long.
        # For typical Korean/English scripts with spaces, we expect <= max_chars.
        self.assertTrue(all(len(s) <= max_chars for s in out), out)

    def test_dense_split_splits_on_commas_and_semicolons(self) -> None:
        text = "Fast pacing: split on commas, semicolons; and keep it readable."
        out = run_short.split_for_captions_dense(text, max_chars=16)
        self.assertTrue(out)
        self.assertTrue(any("commas" in s for s in out))


if __name__ == "__main__":
    unittest.main()

