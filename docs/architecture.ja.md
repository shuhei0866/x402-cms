# x402-cms アーキテクチャ

`x402-cms` は **Agent-oriented CMS** の reference 実装。同じ URL で User-Agent によって render を分岐させる。人間（browser）は無料 HTML、AI エージェントは HTTP 402 → x402 payment → JSON、という構造。

[English](architecture.md)

## 1. システム全体像（target state）

Phase 1 以降を含む全体像。Phase 0 では `JSONRenderer` と `Facilitator` の往復だけが動く。

```mermaid
graph TB
  subgraph "Buyer Side"
    Human["人間（browser）"]
    Agent["AI エージェント（Claude Code / MCP client）"]
  end

  subgraph "x402-cms（Cloud Run service）"
    Router{"User-Agent 判定"}
    HTMLRenderer["HTML renderer<br/>vault 文体の narrative"]
    JSONRenderer["JSON renderer<br/>+ x402 payment middleware"]
    Router -->|"browser"| HTMLRenderer
    Router -->|"agent"| JSONRenderer
  end

  subgraph "Data Layer（GCP）"
    Firestore[("Firestore")]
    SourceCol["source_data collection"]
    ViewsCol["views collection"]
    DigestsCol["digests cache collection"]
    Firestore --- SourceCol
    Firestore --- ViewsCol
    Firestore --- DigestsCol
  end

  subgraph "Indexers（Cloud Scheduler + Cloud Run jobs）"
    GHIndexer["github_indexer<br/>gh CLI で PR/issue/commit を fetch"]
    XIndexer["x_indexer<br/>xurl で X posts を fetch"]
  end

  subgraph "Content Source（vault が source of truth）"
    Vault["Obsidian Vault<br/>x402_digest/views/*.md<br/>frontmatter: published bool"]
    PublishScript["publish_views.py"]
  end

  subgraph "Off-chain Services"
    GitHub[("GitHub<br/>x402-foundation/x402")]
    XAPI[("X API<br/>via xurl")]
  end

  subgraph "On-chain"
    Facilitator["x402.org/facilitator<br/>verify + settle"]
    BaseSepolia[("Base Sepolia / Base<br/>USDC")]
  end

  Human --> Router
  Agent --> Router

  HTMLRenderer --> Firestore
  JSONRenderer --> Firestore
  JSONRenderer -.->|"verify/settle"| Facilitator
  Facilitator --> BaseSepolia

  GHIndexer --> GitHub
  XIndexer --> XAPI
  GHIndexer --> SourceCol
  XIndexer --> SourceCol

  Vault --> PublishScript
  PublishScript --> ViewsCol
```

## 2. リクエストシーケンス（人間 vs エージェント）

同じ URL に対する 2 種類の挙動を時系列で示す。

```mermaid
sequenceDiagram
  participant H as 人間（browser）
  participant A as AI エージェント（MCP client）
  participant S as x402-cms server
  participant F as Facilitator
  participant B as Base Sepolia

  Note over H,A: 同じ URL に対して挙動が分岐する

  H->>S: GET /digest/2026-W19<br/>Accept: text/html
  S->>S: User-Agent 判定（human）
  S-->>H: 200 OK<br/>HTML body（narrative + commentary）

  A->>S: GET /digest/2026-W19<br/>Accept: application/json
  S->>S: User-Agent 判定（agent）
  S-->>A: 402 Payment Required<br/>+ payment-required header

  A->>A: USDC payment payload に sign
  A->>S: GET /digest/2026-W19<br/>X-Payment: signed-payload
  S->>F: verify payment
  F-->>S: verified
  S->>F: settle payment
  F->>B: USDC transfer
  F-->>S: settled
  S-->>A: 200 OK<br/>JSON body（structured digest）
```

## 3. Phase 0 の現状（minimal endpoint）

ここまで実装済みの範囲。content は hardcoded、scheme は `exact/evm`、network は Base Sepolia。

dotted の edge（`verify/settle` と `transfer`）は real payment が来た場合に通る経路を示すが、Phase 0 では実際にはまだ通っていない。curl での動作確認は 402 が返ることまで。

```mermaid
graph LR
  Client["curl / agent"]
  Mid["x402 PaymentMiddlewareASGI"]
  App["FastAPI app.py<br/>GET /digest/test<br/>hardcoded JSON"]
  Fac["x402.org/facilitator"]
  Base[("Base Sepolia<br/>USDC")]

  Client -->|"GET /digest/test"| Mid
  Mid -->|"402 Payment Required"| Client
  Client -->|"GET + X-Payment"| Mid
  Mid -.->|"verify/settle（Phase 0 では未踏）"| Fac
  Fac -.->|"transfer"| Base
  Mid --> App
  App -->|"hardcoded JSON"| Mid
  Mid -->|"200"| Client
```

## 4. データの流れ（vault が draft、Firestore が published）

view content は人間が書く draft（vault）と server が読む published（Firestore）に分かれる。publish step が間に挟まる。

```mermaid
flowchart LR
  subgraph "Local（手元）"
    Obsidian["Obsidian Vault<br/>x402_digest/views/2026-W19.md"]
  end

  subgraph "Manual trigger"
    Publish["publish_views.py<br/>frontmatter published:true のみ sync"]
  end

  subgraph "Server（Cloud Run）"
    DBV["Firestore views collection"]
    DBS["Firestore source_data collection"]
    Render["render layer<br/>views と source を merge"]
    Out["Response<br/>HTML or JSON"]
  end

  subgraph "Automated"
    GH["github_indexer"]
    X["x_indexer"]
  end

  Obsidian --> Publish
  Publish --> DBV
  GH --> DBS
  X --> DBS
  DBV --> Render
  DBS --> Render
  Render --> Out
```

## 5. Public / Private の分離

repo は public、Shuhei 固有の judgement layer のみ gitignore する。

```mermaid
graph TB
  subgraph "Public（OSS reference 実装）"
    Code["code/<br/>indexers, renderers, server"]
    Schema["schema/"]
    Workflow[".github/workflows/"]
    ReadmeFile["README.md / LICENSE"]
  end

  subgraph "Private（gitignore）"
    Config["config/<br/>tracked_handles.yaml<br/>importance_rules.yaml"]
    Prompts["prompts/<br/>commentary_template.md<br/>recommendation_prompt.md"]
    Data["data/<br/>source/ (cache)<br/>views/ (vault mirror)"]
    Env[".env"]
  end

  subgraph "Vault（別 repo / iCloud）"
    VaultDraft["vault: x402_digest/views/<br/>frontmatter: published bool"]
  end

  VaultDraft -.->|"publish_views.py"| Data
```
