"""x402-cms server entrypoint.

Phase 1 dual-render handler. Same URL `/digest/{week}` for both
audiences:

- Humans (User-Agent matches a known browser marker) get a free HTML
  view.
- Agents (the default — anything not recognised as a human browser)
  get a paid JSON view via the x402 protocol: 402 Payment Required
  without a valid `x-payment` header, JSON after `verify_payment` +
  `settle_payment` succeed on the facilitator.

The Phase 0 `PaymentMiddlewareASGI` is intentionally not used. The
middleware is route-scoped and would force a 402 on every caller of the
shared path, which conflicts with the same-URL dual render. We drive
verification and settlement from inside the handler with
`x402HTTPResourceServer` so the human path can short-circuit before any
payment work runs.

Run with:
    uv run uvicorn code.server.main:app --host 0.0.0.0 --port 4021 --reload
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import FastAPIAdapter
from x402.http.types import HTTPRequestContext, RouteConfig
from x402.http.x402_http_server import x402HTTPResourceServer
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.schemas import Network
from x402.server import x402ResourceServer

from code.dispatch import is_agent_request
from code.indexers.x_indexer import load_handle_clusters
from code.observability import access_log_middleware, configure_logging
from code.renderers.digest import (
    DEFAULT_REPO,
    load_digest_bundle,
    render_agent_payload,
    render_html,
)
from code.renderers.digest.i18n import (
    lang_from_accept_language,
    normalize_lang,
)
from code.renderers.digest.topics import (
    TopicRule,
    XKeywordRule,
    load_topics_config,
)

EVM_NETWORK: Network = "eip155:84532"  # Base Sepolia
DIGEST_ROUTE_PATTERN = "GET /digest/*"
DEFAULT_HANDLES_CONFIG_PATH = "/secrets/tracked_handles.yaml"
# Cloud Run mounts each secret as its own directory volume, so a
# second secret cannot share /secrets with the handles file.
DEFAULT_TOPICS_CONFIG_PATH = "/topics/topics.yaml"
STATIC_DIR = Path(__file__).parent / "static"


@dataclass(frozen=True)
class ServerConfig:
    """Server-side env-derived config.

    `evm_address` is required and validated at load time so its type
    is a plain `str` — the handler can pass it to x402 without a
    cast. `gcp_project` is optional (falls back to ADC default).
    """

    evm_address: str
    facilitator_url: str
    gcp_project: str | None
    handles_config_path: str
    topics_config_path: str


def _load_config() -> ServerConfig:
    load_dotenv()
    evm_address = os.getenv("EVM_ADDRESS")
    if not evm_address:
        raise ValueError("EVM_ADDRESS is required in .env")
    return ServerConfig(
        evm_address=evm_address,
        facilitator_url=os.getenv(
            "FACILITATOR_URL", "https://x402.org/facilitator"
        ),
        gcp_project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        handles_config_path=os.getenv(
            "HANDLES_CONFIG_PATH", DEFAULT_HANDLES_CONFIG_PATH
        ),
        topics_config_path=os.getenv(
            "TOPICS_CONFIG_PATH", DEFAULT_TOPICS_CONFIG_PATH
        ),
    )


def _load_handle_clusters_safely(path: str) -> dict[str, str]:
    """Load the curated handle → cluster map; tolerate a missing file.

    In production the Cloud Run Service mounts the secret at this
    path; in local dev the file may not exist (developer is iterating
    on the renderer, not on curation). An empty map degrades the
    renderer gracefully (the Japan section just shows the empty
    state), so a missing file is logged but does not block startup.
    """
    try:
        return load_handle_clusters(path)
    except FileNotFoundError:
        return {}


def _load_topics_safely(
    path: str,
) -> tuple[list[TopicRule], list[XKeywordRule]]:
    """Load the curated topic mapping; tolerate a missing file.

    Same degradation contract as the cluster map: without the file
    the glance block shows "no topics config loaded" instead of a
    distribution, and startup proceeds.
    """
    try:
        return load_topics_config(path)
    except FileNotFoundError:
        return [], []


def _select_lang(request: Request) -> str:
    """Pick the human-view locale: `?lang=` wins, else Accept-Language.

    An explicit query param is honoured (so the toggle and deep links
    are deterministic); otherwise the browser's primary Accept-Language
    tag decides, defaulting to English. Only the chrome is localised —
    the agent JSON path never consults this.
    """
    param = request.query_params.get("lang")
    if param:
        return normalize_lang(param)
    return lang_from_accept_language(request.headers.get("accept-language"))


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    The x402 plumbing (facilitator client, resource server, HTTP server
    wrapper, route declarations) is built once at app construction. The
    facilitator's supported-schemes call is fired in the lifespan so the
    first agent request does not pay that latency.
    """
    configure_logging()
    config = _load_config()
    # Curation inputs are read once at startup — they are deploy-time
    # inputs, not per-request lookups, so a single load is enough and
    # avoids hitting the mounted files on every digest request.
    handle_clusters = _load_handle_clusters_safely(config.handles_config_path)
    topic_rules, x_keywords = _load_topics_safely(config.topics_config_path)

    facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=config.facilitator_url))
    server = x402ResourceServer(facilitator)
    server.register(EVM_NETWORK, ExactEvmServerScheme())

    routes = {
        DIGEST_ROUTE_PATTERN: RouteConfig(
            accepts=[
                PaymentOption(
                    scheme="exact",
                    pay_to=config.evm_address,
                    price="$0.05",
                    network=EVM_NETWORK,
                ),
            ],
            mime_type="application/json",
            description="x402-cms weekly digest — agent JSON view",
        ),
    }
    http_server = x402HTTPResourceServer(server, routes)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            http_server.initialize()
        except Exception:
            # Initialisation is best-effort at startup; the SDK falls
            # back to lazy init on the first request if this raises.
            pass
        try:
            yield
        finally:
            await facilitator.aclose()

    app = FastAPI(title="x402-cms", version="0.1.0", lifespan=lifespan)
    app.middleware("http")(access_log_middleware)
    # The stylesheet is vendored so the human view has no external
    # dependency (no CDN fetch, works under a strict CSP).
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def root() -> dict:
        """Free landing endpoint that advertises the digest route."""
        return {
            "name": "x402-cms",
            "version": "0.1.0",
            "phase": "phase-1",
            "description": (
                "Agent-oriented CMS — same URL, free HTML for humans / "
                "paid JSON for agents"
            ),
            "endpoints": {
                "GET /digest/{week}": (
                    "free HTML for humans, $0.05 USDC paid JSON for agents "
                    "(Base Sepolia)"
                ),
            },
        }

    @app.get("/digest/{week}")
    async def digest(week: str, request: Request) -> Response:
        """Same-URL dual render handler.

        Default route is the agent-paid JSON path; only User-Agents
        recognised as a human browser short-circuit to the free HTML
        view. The dispatch is decided by `is_agent_request` reading
        the User-Agent header.
        """
        if not is_agent_request(request.headers):
            bundle = load_digest_bundle(
                week,
                repo=DEFAULT_REPO,
                project=config.gcp_project,
                handle_clusters=handle_clusters,
                topic_rules=topic_rules,
                x_keywords=x_keywords,
            )
            return HTMLResponse(render_html(bundle, lang=_select_lang(request)))

        adapter = FastAPIAdapter(request)
        context = HTTPRequestContext(
            adapter=adapter,
            path=request.url.path,
            method=request.method,
            payment_header=(
                adapter.get_header("payment-signature")
                or adapter.get_header("x-payment")
            ),
        )

        result = await http_server.process_http_request(context)

        if result.type == "payment-error":
            instructions = result.response
            assert instructions is not None
            return JSONResponse(
                content=instructions.body or {},
                status_code=instructions.status,
                headers=instructions.headers,
            )

        if result.type == "no-payment-required":
            # Defensive: the digest route is registered with payment
            # requirements, so this branch should not normally fire.
            # Serve the free JSON rather than block the caller.
            bundle = load_digest_bundle(
                week,
                repo=DEFAULT_REPO,
                project=config.gcp_project,
                handle_clusters=handle_clusters,
                topic_rules=topic_rules,
                x_keywords=x_keywords,
            )
            return JSONResponse(content=render_agent_payload(bundle))

        # payment-verified: render, then settle on the facilitator and
        # attach settlement headers to the response.
        assert result.payment_payload is not None
        assert result.payment_requirements is not None

        bundle = load_digest_bundle(
            week,
            repo=DEFAULT_REPO,
            project=config.gcp_project,
            handle_clusters=handle_clusters,
            topic_rules=topic_rules,
            x_keywords=x_keywords,
        )
        payload = render_agent_payload(bundle)

        settle_result = await http_server.process_settlement(
            result.payment_payload,
            result.payment_requirements,
            context=context,
        )

        if not settle_result.success:
            instructions = settle_result.response
            assert instructions is not None
            return JSONResponse(
                content=instructions.body or {},
                status_code=instructions.status,
                headers=instructions.headers,
            )

        return JSONResponse(content=payload, headers=settle_result.headers)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=4021)
