import os
import subprocess
import sys
import unittest
from pathlib import Path

from scripts.check_commit_message import validate_subject


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_commit_message.py"


class CommitMessageTestCase(unittest.TestCase):
    def test_accepts_required_scope_and_breaking_marker(self):
        self.assertIsNone(validate_subject("feat(rules): update duplicate threshold"))
        self.assertIsNone(validate_subject("feat(api)!: replace subscription endpoints"))

    def test_rejects_missing_or_invalid_scope(self):
        self.assertIsNotNone(validate_subject("feat: add rule engine"))
        self.assertIsNotNone(validate_subject("feat(Rules): add rule engine"))
        self.assertIsNotNone(validate_subject("Add rule engine"))

    def test_reads_subject_from_environment(self):
        environment = dict(os.environ, COMMIT_SUBJECT="fix(quote): mark lowest platform")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--env", "COMMIT_SUBJECT"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
