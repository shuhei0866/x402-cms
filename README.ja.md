# x402-cms

x402 課金対応 CMS — HTTP 402 マイクロペイメントで AI エージェント向けに content を delivery する。**人間には無料、エージェントには課金。**

[English](README.md)

## コンセプト

同じ URL でも、リクエスト元によって render を分岐させる:

- **人間（browser）アクセス** → 無料 HTML
- **AI エージェントアクセス** → 402 Payment Required、x402 で支払った後に JSON

「Agent-oriented CMS」という新カテゴリの reference 実装。x402 のような protocol が可能にする「広告依存型 → エージェント課金型」への transition を体現する構造。

## 最初のユースケース: x402 dev digest

x402 ecosystem の動向（merged / active / 新規 PR、活発な issue 議論、builder の X 発信、日本コミュニティの signal）を `/digest/{YYYY-Www}` で、人間の読者にも AI エージェントにも届ける。

人間向け view は「表示する」だけでなく「週次レビューに使える」ことを目標に設計している:

- **This week at a glance** — ファーストビューのダッシュボード。誰が動いたか（author 別の活動集約、bot は脚注に分離）、何が注目されているか（PR と issue を comments 数で単一ランキング）、どの領域で話されているか（topic / cluster / keyword の分布）
- **逆ピラミッドのセクション構成** — 進行中の議論を先頭に、議論が熱い順で読ませる。閉じられた新規 PR とリプライは `<details>` に畳む（畳むだけで、何も捨てない）
- **ナビゲーション** — 公開済み記事のトップと一覧、安定 id 付きのsection nav、空weekを飛ばす前後リンクで巡回のループを閉じる

並べ替えと折りたたみの規則はすべて機械的（リプライか否か、open か closed か、comments 数、時系列）に限定している。どの signal をどの topic に数えるかは curation ファイル（`config/topics.yaml`、gitignored。`config/topics.example.yaml` を動くテンプレートとして同梱）が持つ — **対応表そのものが編集行為であり、renderer は数えるだけ**。engagement 指標（likes）は意図的にソートに使わない。likes はフォロワー数の関数であり、signal を追う目的とずれるからである。

## Tech スタック

- FastAPI (Python 3.11+)
- [`python/x402`](https://github.com/x402-foundation/x402/tree/main/python/x402)（server SDK、scheme: `exact/evm`、Base Sepolia）
- Pico CSS classless build を vendor — markup は class 無しの semantic HTML のまま
- Cloud Run Service（render）+ Cloud Run Jobs（indexers）、Cloud Scheduler の weekly + daily cron で駆動
- Firestore（4 collections: PRs / issues / X posts / commentary）
- GitHub Search API と X API v2 は httpx で直接叩く（image に CLI 依存を持ち込まない）

## ステータス

Phase 0〜4 が **Base Sepolia testnet** 上で本番稼働している: 実 settlement 付きの dual render、weekly + daily の indexer 群（PR / issue / X posts）、curation 済み commentary パイプライン（vault → publish → Firestore）、情報設計済みの人間向け view。人間向けのトップ、記事一覧、空weekを飛ばすnavigationは、公開済みweek-level commentaryから生成する。Phase 5の前に、[Agent-friendly Advantage Benchmark R0](docs/agent-friendly-advantage-benchmark-r0.ja.md)で、有料JSONが無料HTML経路より実際にエージェントの作業を減らすかを測る。Phase 5（Base mainnet化とbatch-settlement schemeへの切り替え）は、その証拠をgateとする。

## セットアップ

**前提**: [`uv`](https://docs.astral.sh/uv/) がインストール済み、Python 3.11+。

```bash
uv sync
cp .env.example .env   # EVM_ADDRESS を自分の Base Sepolia アドレスに設定

# 任意: 自分の curation を作る（どちらも gitignored）
cp config/tracked_handles.example.yaml config/tracked_handles.yaml
cp config/topics.example.yaml config/topics.yaml

HANDLES_CONFIG_PATH=config/tracked_handles.yaml \
TOPICS_CONFIG_PATH=config/topics.yaml \
uv run uvicorn code.server.main:app --host 0.0.0.0 --port 4021 --reload
```

config の env 2 つを渡さなくても server は起動する。cluster 系セクションは明示的な空表示になり、glance は「no topics config loaded」と表示する — 縮退モードは必ず見える形にし、静かに壊れない。

dual render を動作確認する:

```bash
# machine-readableなroot endpoint — 200 OK
curl http://localhost:4021/

# 人間向けトップと公開済み記事一覧 — 200 OK、HTML
curl -A "Mozilla/5.0" http://localhost:4021/
curl -A "Mozilla/5.0" http://localhost:4021/archive

# 人間向け view — 200 OK、HTML が返る
curl -A "Mozilla/5.0" http://localhost:4021/digest/2026-W27

# エージェント向け view — 402 Payment Required が返り、
# `payment-required` header に x402 payload が encoded されている
curl -i http://localhost:4021/digest/2026-W27
```

## アーキテクチャ

[`docs/architecture.ja.md`](docs/architecture.ja.md) を参照。以下を含む:

- Component diagram
- Request sequence（人間 vs エージェント）
- Data flow（indexers → Firestore → render、vault → publish → Firestore）
- Deploy topology（Service / Jobs / Schedulers / Secret Manager）
- Public / private layer の分離

## ライセンス

MIT。vendor した Pico CSS build は自身の MIT copyright ヘッダを保持している。
