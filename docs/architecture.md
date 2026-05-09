# x402-cms Architecture

`x402-cms` is a reference implementation of an **Agent-oriented CMS**. It serves the same URL with two different renderings based on the requester: a free HTML page for humans (browsers), and a paid JSON response for AI agents via HTTP 402 + the x402 protocol.

[日本語版](architecture.ja.md)

## 1. System overview (target state)

The full picture once Phase 1+ is in place. In Phase 0, only the `JSONRenderer` and `Facilitator` round-trip is wired up.

```mermaid
graph TB
  subgraph "Buyer Side"
    Human["Human (browser)"]
    Agent["AI agent (Claude Code / MCP client)"]
  end

  subgraph "x402-cms (Cloud Run service)"
    Router{"User-Agent dispatch"}
    HTMLRenderer["HTML renderer<br/>narrative in vault style"]
    JSONRenderer["JSON renderer<br/>+ x402 payment middleware"]
    Router -->|"browser"| HTMLRenderer
    Router -->|"agent"| JSONRenderer
  end

  subgraph "Data Layer (GCP)"
    Firestore[("Firestore")]
    SourceCol["source_data collection"]
    ViewsCol["views collection"]
    DigestsCol["digests cache collection"]
    Firestore --- SourceCol
    Firestore --- ViewsCol
    Firestore --- DigestsCol
  end

  subgraph "Indexers (Cloud Scheduler + Cloud Run jobs)"
    GHIndexer["github_indexer<br/>fetches PR/issue/commit via gh CLI"]
    XIndexer["x_indexer<br/>fetches X posts via xurl"]
  end

  subgraph "Content Source (vault is the source of truth)"
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

## 2. Request sequence (human vs agent)

The two behaviors at the same URL, shown over time.

```mermaid
sequenceDiagram
  participant H as Human (browser)
  participant A as AI agent (MCP client)
  participant S as x402-cms server
  participant F as Facilitator
  participant B as Base Sepolia

  Note over H,A: Same URL, different behavior

  H->>S: GET /digest/2026-W19<br/>Accept: text/html
  S->>S: dispatch (human)
  S-->>H: 200 OK<br/>HTML body (narrative + commentary)

  A->>S: GET /digest/2026-W19<br/>Accept: application/json
  S->>S: dispatch (agent)
  S-->>A: 402 Payment Required<br/>+ payment-required header

  A->>A: sign USDC payment payload
  A->>S: GET /digest/2026-W19<br/>X-Payment: signed-payload
  S->>F: verify payment
  F-->>S: verified
  S->>F: settle payment
  F->>B: USDC transfer
  F-->>S: settled
  S-->>A: 200 OK<br/>JSON body (structured digest)
```

## 3. Phase 0 (minimal endpoint, currently working)

What the repository runs today. Content is hardcoded; scheme is `exact/evm`; network is Base Sepolia.

The dotted edges (`verify/settle`, `transfer`) show the path that real payments would take but are not yet exercised in Phase 0 — the local curl test only verifies the 402 response.

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
  Mid -.->|"verify/settle (not yet exercised in Phase 0)"| Fac
  Fac -.->|"transfer"| Base
  Mid --> App
  App -->|"hardcoded JSON"| Mid
  Mid -->|"200"| Client
```

## 4. Data flow (vault drafts, Firestore publishes)

View content is split between drafts written by humans (vault) and the published copy the server reads (Firestore). A publish step sits between them.

```mermaid
flowchart LR
  subgraph "Local"
    Obsidian["Obsidian Vault<br/>x402_digest/views/2026-W19.md"]
  end

  subgraph "Manual trigger"
    Publish["publish_views.py<br/>syncs only frontmatter published:true"]
  end

  subgraph "Server (Cloud Run)"
    DBV["Firestore views collection"]
    DBS["Firestore source_data collection"]
    Render["render layer<br/>merges views with source"]
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

## 5. Public / private separation

The repository is public, but the curator's judgement layer is gitignored.

```mermaid
graph TB
  subgraph "Public (OSS reference implementation)"
    Code["code/<br/>indexers, renderers, server"]
    Schema["schema/"]
    Workflow[".github/workflows/"]
    ReadmeFile["README.md / LICENSE"]
  end

  subgraph "Private (gitignored)"
    Config["config/<br/>tracked_handles.yaml<br/>importance_rules.yaml"]
    Prompts["prompts/<br/>commentary_template.md<br/>recommendation_prompt.md"]
    Data["data/<br/>source/ (cache)<br/>views/ (vault mirror)"]
    Env[".env"]
  end

  subgraph "Vault (separate repo / iCloud)"
    VaultDraft["vault: x402_digest/views/<br/>frontmatter: published bool"]
  end

  VaultDraft -.->|"publish_views.py"| Data
```
