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

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import FastAPIAdapter
from x402.http.types import HTTPRequestContext, RouteConfig
from x402.http.x402_http_server import x402HTTPResourceServer
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.schemas import Network
from x402.server import x402ResourceServer

from code.dispatch import is_agent_request
from code.renderers.digest import (
    DEFAULT_REPO,
    read_week,
    render_agent_payload,
    render_html,
)

EVM_NETWORK: Network = "eip155:84532"  # Base Sepolia
DIGEST_ROUTE_PATTERN = "GET /digest/*"


def _load_config() -> dict[str, str | None]:
    load_dotenv()
    evm_address = os.getenv("EVM_ADDRESS")
    if not evm_address:
        raise ValueError("EVM_ADDRESS is required in .env")
    return {
        "evm_address": evm_address,
        "facilitator_url": os.getenv("FACILITATOR_URL", "https://x402.org/facilitator"),
        "gcp_project": os.getenv("GOOGLE_CLOUD_PROJECT"),
    }


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    The x402 plumbing (facilitator client, resource server, HTTP server
    wrapper, route declarations) is built once at app construction. The
    facilitator's supported-schemes call is fired in the lifespan so the
    first agent request does not pay that latency.
    """
    config = _load_config()

    facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=config["facilitator_url"]))
    server = x402ResourceServer(facilitator)
    server.register(EVM_NETWORK, ExactEvmServerScheme())

    routes = {
        DIGEST_ROUTE_PATTERN: RouteConfig(
            accepts=[
                PaymentOption(
                    scheme="exact",
                    pay_to=config["evm_address"],
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
            prs = read_week(week, project=config["gcp_project"])
            return HTMLResponse(render_html(prs, week, DEFAULT_REPO))

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
            prs = read_week(week, project=config["gcp_project"])
            return JSONResponse(content=render_agent_payload(prs, week, DEFAULT_REPO))

        # payment-verified: render, then settle on the facilitator and
        # attach settlement headers to the response.
        assert result.payment_payload is not None
        assert result.payment_requirements is not None

        prs = read_week(week, project=config["gcp_project"])
        payload = render_agent_payload(prs, week, DEFAULT_REPO)

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
