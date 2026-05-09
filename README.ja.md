# x402-cms

x402 課金対応 CMS — HTTP 402 マイクロペイメントで AI エージェント向けに content を delivery する。**人間には無料、エージェントには課金。**

[English](README.md)

## コンセプト

同じ URL でも、リクエスト元によって render を分岐させる:

- **人間（browser）アクセス** → 無料 HTML
- **AI エージェントアクセス** → 402 Payment Required、x402 で支払った後に JSON

「Agent-oriented CMS」という新カテゴリの reference 実装。x402 のような protocol が可能にする「広告依存型 → エージェント課金型」への transition を体現する構造。

## 最初のユースケース: x402 dev digest

x402 ecosystem の動向（merged PR、open design discussion、builder の X 発信、日本コミュニティの signal）を weekly digest として、人間の読者にも AI エージェントにも届ける。

## Tech スタック

- FastAPI (Python 3.11+)
- [`python/x402`](https://github.com/x402-foundation/x402/tree/main/python/x402)（server SDK、scheme: `exact/evm`）
- Cloud Run（hosting）
- Firestore（DB）
- Cloud Scheduler + Cloud Run jobs（indexers）
- [`xurl`](https://github.com/xdevplatform/xurl)（X API CLI、X indexer 用）

## ステータス

**Phase 0** — Base Sepolia testnet で minimal endpoint が動作する状態。

## セットアップ (Phase 0)

**前提**: [`uv`](https://docs.astral.sh/uv/) がインストール済み、Python 3.11+。

```bash
uv sync
cp .env.example .env  # EVM_ADDRESS を自分の Base Sepolia testnet アドレスに設定
uv run uvicorn app:app --host 0.0.0.0 --port 4021 --reload
```

payment flow を動作確認する:

```bash
# 無料の root endpoint — 200 OK が返る
curl http://localhost:4021/

# 課金 endpoint — 402 Payment Required が返る
# `payment-required` header に x402 payload が encoded されている
curl -i http://localhost:4021/digest/test
```

## アーキテクチャ

[`docs/architecture.ja.md`](docs/architecture.ja.md) を参照。以下を含む:

- Component diagram（target state）
- Request sequence（人間 vs エージェント）
- Phase 0 の最小 flow
- Data flow（vault → publish → Firestore → render）
- Public / private layer の分離

## ライセンス

MIT
