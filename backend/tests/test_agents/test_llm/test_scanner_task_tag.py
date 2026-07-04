"""Phase 1: the high-volume scanner narration calls are routed with task="scanner"."""
import inspect

from services.background_scanner import scanner


def test_scanner_generate_calls_are_tagged():
    src = inspect.getsource(scanner)
    assert src.count('task="scanner"') >= 2
    # and the old untagged form is gone
    assert "await llm.generate(messages)\n" not in src
