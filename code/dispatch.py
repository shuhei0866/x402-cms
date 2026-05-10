"""User-Agent based agent vs human dispatcher.

Agent-paid is the default. An unknown or empty User-Agent is treated as
an automated agent, so the URL's default response is 402 Payment
Required. Requests fall through to the free human HTML path only when
the User-Agent contains a known browser marker (Mozilla, Chrome,
Safari, Firefox, Edge, Opera, Brave). This expresses the x402 narrative
— "ad-funded is the legacy default, agent-paid is the new one" — at
the dispatch layer itself.

The heuristic is intentionally small so the call sites stay decoupled
from how a human is recognised. Future iterations may sniff the Accept
header, look for signed agent claims, or read a query parameter; the
contract `headers -> bool` is meant to stay stable.
"""

from __future__ import annotations

from collections.abc import Mapping

# Lowercase substrings whose presence in the User-Agent marks a request
# as a human browser. Almost every modern browser sends a UA that
# begins with `Mozilla/5.0` for historical compatibility, but listing
# the others explicitly makes the whitelist's intent legible.
HUMAN_BROWSER_KEYWORDS: tuple[str, ...] = (
    "mozilla",
    "chrome",
    "safari",
    "firefox",
    "edg",
    "opera",
    "brave",
)


def is_agent_request(headers: Mapping[str, str]) -> bool:
    """Return True when the request should be served the paid agent path.

    Default-allow agent path: an unknown or empty User-Agent returns
    True, so the URL's default response is 402 Payment Required. Only
    requests whose User-Agent matches one of `HUMAN_BROWSER_KEYWORDS`
    (case-insensitive) fall through to the free human HTML path.
    """
    user_agent = headers.get("user-agent") or headers.get("User-Agent") or ""
    if not user_agent:
        return True
    ua = user_agent.lower()
    return not any(keyword in ua for keyword in HUMAN_BROWSER_KEYWORDS)
