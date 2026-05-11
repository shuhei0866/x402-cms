"""x402-cms dogfood — drive the deployed service through one paid call.

Uses the python/x402 buyer client (the same SDK x402-cms serves with on
the server side) to exercise the live Cloud Run deployment end-to-end:

1. Derive an EVM signer from `BUYER_MNEMONIC` at m/44'/60'/0'/0/0.
2. GET `DOGFOOD_URL` (default: the deployed `/digest/{week}`).
3. Let `x402AsyncTransport` turn the 402 into a signed EIP-3009
   authorization, re-request with `x-payment`, and surface the 200.
4. Print the response status, the relevant x402 headers, and the
   decoded `x-payment-response` settlement record (carries the on-chain
   tx hash so the run can be cross-checked on a Base Sepolia explorer).

Run:

    BUYER_MNEMONIC="word1 word2 ..." \\
    uv run python scripts/dogfood_payment_loop.py

Optional overrides:

    DOGFOOD_URL=...                # default: deployed /digest/2026-W19
    BUYER_DERIVATION_PATH=...      # default: m/44'/60'/0'/0/0
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys

from dotenv import load_dotenv

DEFAULT_URL = (
    "https://x402-cms-956940181160.asia-northeast1.run.app/digest/2026-W19"
)
DEFAULT_DERIVATION_PATH = "m/44'/60'/0'/0/0"
BASE_SEPOLIA: str = "eip155:84532"


def _derive_account(mnemonic: str, derivation_path: str):
    from eth_account import Account

    Account.enable_unaudited_hdwallet_features()
    return Account.from_mnemonic(mnemonic, account_path=derivation_path)


def _decode_payment_response(header_value: str) -> dict | None:
    try:
        decoded = base64.b64decode(header_value)
        return json.loads(decoded)
    except Exception:
        return None


async def _main() -> int:
    load_dotenv()

    mnemonic = os.getenv("BUYER_MNEMONIC")
    if not mnemonic:
        print("BUYER_MNEMONIC is not set (env or .env).", file=sys.stderr)
        print(
            "Export from agent-cli-legacy and paste into x402-cms/.env:\n"
            "  node ~/Documents/agent-cli-legacy/dist/index.js"
            " wallet export --name explorer-agent",
            file=sys.stderr,
        )
        return 2

    url = os.getenv("DOGFOOD_URL", DEFAULT_URL)
    derivation_path = os.getenv("BUYER_DERIVATION_PATH", DEFAULT_DERIVATION_PATH)

    account = _derive_account(mnemonic, derivation_path)
    print(f"buyer address: {account.address}")
    print(f"derivation:    {derivation_path}")
    print(f"target URL:    {url}")
    print(f"network:       {BASE_SEPOLIA} (Base Sepolia)")
    print()

    from x402 import SchemeRegistration, prefer_network, prefer_scheme, x402ClientConfig
    from x402.http.clients.httpx import wrapHttpxWithPaymentFromConfig
    from x402.mechanisms.evm.exact import ExactEvmScheme

    config = x402ClientConfig(
        schemes=[
            SchemeRegistration(
                network=BASE_SEPOLIA,
                client=ExactEvmScheme(signer=account),
            ),
        ],
        policies=[prefer_network(BASE_SEPOLIA), prefer_scheme("exact")],
    )

    async with wrapHttpxWithPaymentFromConfig(config, timeout=60.0) as client:
        response = await client.get(url)

    print(f"HTTP {response.status_code}")
    for key, value in response.headers.items():
        lk = key.lower()
        if "payment" in lk:
            preview = value if len(value) <= 200 else value[:200] + f"... ({len(value)} bytes)"
            print(f"  {key}: {preview}")
    print()

    if response.status_code != 200:
        print("FAILED — non-200 response.")
        print(response.text[:2000])
        return 1

    body = response.json()
    print("agent JSON payload (first 800 chars):")
    print(json.dumps(body, indent=2, ensure_ascii=False)[:800])
    print()

    response_header = response.headers.get("payment-response") or response.headers.get(
        "x-payment-response"
    )
    if response_header:
        decoded = _decode_payment_response(response_header)
        if decoded:
            print("decoded x-payment-response:")
            print(json.dumps(decoded, indent=2))
            tx = decoded.get("transaction") or decoded.get("txHash") or decoded.get("tx")
            if tx:
                print()
                print(f"  on-chain tx: {tx}")
                print(
                    "  inspect at: "
                    f"https://sepolia.basescan.org/tx/{tx}"
                )
        else:
            print("(could not decode x-payment-response)")
            print(response_header[:200])

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
