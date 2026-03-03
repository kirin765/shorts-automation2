import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestScheduledFlowTopicUniqueness(unittest.TestCase):
    def test_run_scheduled_blocks_queue_when_topic_count_is_short(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        source_script = repo_root / "scripts" / "run_scheduled.sh"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scripts_dir = root / "scripts"
            bin_dir = root / "bin"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            bin_dir.mkdir(parents=True, exist_ok=True)

            target_script = scripts_dir / "run_scheduled.sh"
            target_script.write_text(source_script.read_text(encoding="utf-8"), encoding="utf-8")
            target_script.chmod(target_script.stat().st_mode | stat.S_IXUSR)

            fake_python = bin_dir / "python3"
            fake_python.write_text(
                """#!/usr/bin/env bash
set -euo pipefail

if [[ "$1" == "scripts/generate_topics.py" ]]; then
  out="jobs/topics.txt"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --out) out="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  mkdir -p "$(dirname "$out")"
  printf "only-one-topic\\n" > "$out"
  exit 0
fi

if [[ "$1" == "scripts/run_daily.py" ]]; then
  touch run_daily_called.marker
  exit 0
fi

echo "unexpected python3 call: $*" >&2
exit 90
""",
                encoding="utf-8",
            )
            fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)

            env = os.environ.copy()
            env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
            env["COUNT"] = "2"
            env["CONFIG"] = "ENV"
            env["NO_UPLOAD"] = "1"
            env["NICHE"] = "tech"
            env["STYLE"] = "short"
            env["TONE"] = "fast"

            proc = subprocess.run(
                ["bash", str(target_script)],
                cwd=root,
                text=True,
                capture_output=True,
                env=env,
            )

            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("topic generation failed to provide unique set", combined)
            self.assertFalse((root / "run_daily_called.marker").exists())


if __name__ == "__main__":
    unittest.main()
