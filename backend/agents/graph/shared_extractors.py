"""Shared, market-agnostic LLM-response extraction helpers.

Used by the US (nodes.py) and coin (coin_nodes.py) stacks. The KR stack
(kr_stock_nodes/helpers.py) intentionally keeps its OWN Korean-language
variants and must NOT import from here.
"""


def extract_key_factors(response: str) -> list[str]:
    """Extract key factors (bullets / numbered items) from an LLM response."""
    factors = []
    lines = response.split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith(("-", "•", "*")) or (line and line[0].isdigit() and "." in line[:3]):
            clean = line.lstrip("-•*0123456789. ").strip()
            if clean and len(clean) > 10:
                factors.append(clean[:200])
    return factors[:5]


def extract_bull_case(response: str) -> str:
    """Extract the first 500 chars starting at the word 'bull'."""
    lower = response.lower()
    if "bull" in lower:
        start = lower.find("bull")
        return response[start : start + 500]
    return ""


def extract_bear_case(response: str) -> str:
    """Extract the first 500 chars starting at the word 'bear'."""
    lower = response.lower()
    if "bear" in lower:
        start = lower.find("bear")
        return response[start : start + 500]
    return ""
