"""The ONLY place that spawns subprocesses for the LLM layer.

Security: argv is passed as a list to `create_subprocess_exec` (never a shell
string), so arbitrary market/news text in the prompt cannot be interpreted as
shell. On timeout the child is killed and reaped.
"""
import asyncio
from typing import Optional


async def run_cli(
    argv: list[str],
    *,
    stdin: Optional[str] = None,
    timeout: float,
    cwd: str,
) -> tuple[int, str, str]:
    """Run `argv` (no shell), optionally feeding `stdin`, returning
    (returncode, stdout, stderr). Raises TimeoutError (and kills the child) on
    timeout."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin.encode() if stdin is not None else None),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"CLI timed out after {timeout}s: {argv[0]}")
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise
    return (
        proc.returncode if proc.returncode is not None else -1,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )
