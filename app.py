"""x402-cms — Phase 0 minimal endpoint.

Run with:
    uv run uvicorn app:app --host 0.0.0.0 --port 4021 --reload

Phase 0 scope:
- Single paid endpoint GET /digest/test returning a hardcoded JSON digest.
- exact/evm scheme on Base Sepolia.
- Real content generation arrives in Phase 1+.
"""

import os

from dotenv import load_dotenv
from fastapi import FastAPI

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.schemas import Network
from x402.server import x402ResourceServer

load_dotenv()

EVM_ADDRESS = os.getenv("EVM_ADDRESS")
EVM_NETWORK: Network = "eip155:84532"  # Base Sepolia
FACILITATOR_URL = os.getenv("FACILITATOR_URL", "https://x402.org/facilitator")

if not EVM_ADDRESS:
    raise ValueError("EVM_ADDRESS is required in .env")


app = FastAPI(title="x402-cms", version="0.1.0")

facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
server = x402ResourceServer(facilitator)
server.register(EVM_NETWORK, ExactEvmServerScheme())

routes = {
    "GET /digest/test": RouteConfig(
        accepts=[
            PaymentOption(
                scheme="exact",
                pay_to=EVM_ADDRESS,
                price="$0.01",
                network=EVM_NETWORK,
            ),
        ],
        mime_type="application/json",
        description="x402-cms test digest (Phase 0 hardcoded response)",
    ),
}

app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)


@app.get("/")
async def root():
    """Health-check / landing endpoint (free)."""
    return {
        "name": "x402-cms",
        "version": "0.1.0",
        "phase": "phase-0",
        "description": "Agent-oriented CMS — pay per agent request via x402",
        "endpoints": {
            "GET /digest/test": "$0.01 USDC per call (Base Sepolia testnet)",
        },
    }


@app.get("/digest/test")
async def digest_test():
    """Hardcoded test digest used to verify the x402 payment flow in Phase 0."""
    return {
        "version": "0.1.0",
        "phase": "phase-0",
        "digest_type": "test",
        "week": "2026-W19",
        "message": "x402-cms Phase 0 hardcoded response. Real digest content comes in Phase 1.",
        "sections": {
            "github": [],
            "x_section": [],
            "japan_community": [],
            "agent_recommendations": [
                {
                    "id": "test-001",
                    "title": "Phase 0 dummy recommendation",
                    "why": "Hardcoded so we can verify the x402 payment flow end-to-end.",
                }
            ],
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=4021)
