# x402-cms アーキテクチャ

`x402-cms` は **Agent-oriented CMS** のリファレンス実装である。同じ URL で
リクエスタに応じて 2 種類のレンダリングを返す: 人間 (ブラウザ) には無料
HTML、AI agent には HTTP 402 + x402 プロトコル経由で有料 JSON。

[English](architecture.md)

Phase 0〜4 が本番稼働中。Phase 5 (mainnet 化 + batch-settlement scheme への
切替) はロードマップに残っている。現状の決済は **Base Sepolia testnet の
USDC** を `x402.org/facilitator` 経由で扱う。人間向け view は情報設計を
一巡済み: ファーストビューのダッシュボード (This week at a glance)、
議論が熱い順のセクション構成、量の多い content の機械的な折りたたみ、
ページ内ナビゲーションを備える。

## 1. システム全体像

```mermaid
graph TB
  subgraph Buyer["Buyer 側"]
    Human["人間 (ブラウザ)"]
    Agent["AI agent<br/>(MCP / dogfood script)"]
  end

  subgraph Service["Cloud Run Service: x402-cms"]
    Dispatch{"User-Agent<br/>dispatch"}
    Bundle["load_digest_bundle"]
    HTML["render_html"]
    JSON["render_agent_payload<br/>+ x402 payment gate"]
    Dispatch -->|"browser"| Bundle
    Dispatch -->|"agent"| Bundle
    Bundle --> HTML
    Bundle --> JSON
  end

  subgraph FS["Firestore (renderer の唯一の read 面)"]
    SrcCol["source_data<br/>(PRs: merged / active / new)"]
    IssueCol["issues<br/>(活発な議論)"]
    XCol["x_posts<br/>(tweets)"]
    CommCol["commentary<br/>(Shuhei の解釈)"]
  end

  subgraph Jobs["Cloud Run Jobs (週次・月 + 日次、09:00 JST)"]
    GHJob["x402-cms-indexer<br/>httpx + GitHub Search"]
    IssueJob["x402-cms-issue-indexer<br/>httpx + GitHub Search"]
    XJob["x402-cms-x-indexer<br/>httpx + X API v2"]
  end

  subgraph Skills["Claude Code skills (手動)"]
    Reindex["/x402-reindex"]
    Survey["/x402-survey"]
    Publish["/x402-publish"]
  end

  subgraph Vault["Obsidian Vault (private repo)"]
    VaultDir["x402_digest/views/<br/>YYYY-Www-slug.md"]
  end

  subgraph Sec["Secret Manager"]
    Bearer["x402-cms-x-bearer"]
    Handles["x402-cms-tracked-handles<br/>(curated handles + clusters)"]
    Topics["x402-cms-topics<br/>(scope/keyword → category 対応表)"]
  end

  subgraph Off["Off-chain"]
    GitHub[("GitHub<br/>x402-foundation/x402")]
    XAPI[("X API v2")]
  end

  subgraph On["On-chain (Base Sepolia)"]
    Fac["x402.org/facilitator"]
    USDC[("USDC")]
  end

  Human --> Dispatch
  Agent --> Dispatch

  Bundle --> SrcCol
  Bundle --> IssueCol
  Bundle --> XCol
  Bundle --> CommCol
  Handles -.->|"file mount"| Service
  Topics -.->|"file mount"| Service

  GHJob --> GitHub
  GHJob --> SrcCol
  IssueJob --> GitHub
  IssueJob --> IssueCol
  XJob --> XAPI
  XJob --> XCol
  Bearer -.->|"env var"| XJob
  Handles -.->|"file mount"| XJob

  Reindex -.->|"trigger"| GHJob
  Reindex -.->|"trigger"| IssueJob
  Reindex -.->|"trigger"| XJob
  Survey -.->|"read-only"| FS
  VaultDir -->|"manual"| Publish
  Publish --> CommCol

  JSON -.->|"verify + settle"| Fac
  Fac --> USDC
```

設計上の要点:

- **同じ URL を User-Agent で振り分け**。`code/dispatch.py` がブラウザ
  marker (Mozilla / Chrome / Safari / …) を小さなホワイトリストで判定し、
  それ以外はデフォルトで agent 経路に流す。
- **リクエスト時の read 面は Firestore に閉じる**。4 collection、間に
  cache を置かない。GitHub / X を叩くのは Job だけで (週次が先週を確定し、
  日次が `--current` で進行中の週を更新する)、Service は render 時に
  外部 API を呼ばない。
- **curation はコードではなくファイルが持つ**。Service と X indexer Job
  は同じ Secret Manager (`x402-cms-tracked-handles`) を読み、Service は
  加えて `x402-cms-topics` を mount する。cluster 分類、fetch handle
  集合、glance の topic 分布が curation ファイルとずれることはない。
- **人間向け view は逆ピラミッド + 機械的折りたたみ**。ファーストビューに
  ダッシュボード (誰が動いたか / 何が注目か / どの領域の話か) を置き、
  議論セクションは comments 数の多い順に並べ、閉じられた新規 PR と
  リプライは `<details>` に畳む。並べ替えと折りたたみの規則はすべて機械的
  (リプライか否か、open か closed か、comments 数、時系列) で、engagement
  指標 (likes) は意図的にソートに使わない。topic 分布は curated な
  `topics.yaml` への表引きであり、**対応表そのものが編集行為、renderer は
  数えるだけ**。
- **LLM は judgment の下流にのみ入る**。`/x402-survey` は retrieval +
  clustering まで。observation と hypothesis は常に Shuhei が手で先に
  書く (Phase 4 の設計原則)。

## 2. リクエストシーケンス (人間 vs agent)

```mermaid
sequenceDiagram
  participant H as 人間 (browser)
  participant A as AI agent
  participant S as x402-cms Service
  participant F as Facilitator
  participant B as Base Sepolia

  Note over H,A: 同じ URL、振る舞いは別

  H->>S: GET /digest/2026-W21<br/>Mozilla/...
  S->>S: dispatch (human)
  S-->>H: 200 OK · HTML

  A->>S: GET /digest/2026-W21<br/>python-httpx/...
  S->>S: dispatch (agent)
  S-->>A: 402 Payment Required<br/>+ payment-required header

  A->>A: EIP-3009 USDC authorization に署名
  A->>S: GET /digest/2026-W21<br/>X-Payment: signed
  S->>F: verify
  F-->>S: ok
  S->>F: settle
  F->>B: USDC 転送
  F-->>S: settled
  S-->>A: 200 OK · JSON<br/>+ payment-response header
```

## 3. データフロー

```mermaid
flowchart LR
  subgraph Src["Source signals"]
    GH["GitHub API"]
    XAPI["X API v2"]
  end

  subgraph Ingest["Ingest"]
    direction TB
    Cron["Cloud Scheduler<br/>週次・月 + 日次<br/>09:00 JST"]
    Manual["/x402-reindex<br/>週中"]
    GHJob["github_indexer Job<br/>(merged / active / new)"]
    IssJob["issue_indexer Job"]
    XJob["x_indexer Job"]
    Cron --> GHJob
    Cron --> IssJob
    Cron --> XJob
    Manual --> GHJob
    Manual --> IssJob
    Manual --> XJob
  end

  subgraph Curate["Curate (人間)"]
    direction TB
    Survey["/x402-survey<br/>retrieval + clustering"]
    Vault["vault: YYYY-Www-slug.md<br/>frontmatter で固定する<br/>published / week_level /<br/>target_refs / recommended_rank / tldr"]
    PubSkill["/x402-publish<br/>scan + validate + upsert"]
    Survey -.->|"candidate surface"| Vault
    Vault --> PubSkill
  end

  subgraph FS["Firestore"]
    Srcd["source_data"]
    Iss["issues"]
    Xp["x_posts"]
    Cm["commentary"]
  end

  subgraph Serve["Cloud Run Service"]
    Bundle["load_digest_bundle"]
    HTML["render_html"]
    JSON["render_agent_payload"]
  end

  GH --> GHJob --> Srcd
  GH --> IssJob --> Iss
  XAPI --> XJob --> Xp
  PubSkill --> Cm

  Srcd --> Bundle
  Iss --> Bundle
  Xp --> Bundle
  Cm --> Bundle
  Bundle --> HTML
  Bundle --> JSON
```

補足:

- vault 自体が private git repo (`shuhei0866/personal-notes`)。編集履歴は
  git が持ち、Firestore は片道の publish 先。
- `published: false` で unpublish (Firestore doc を削除して renderer から
  見えなくする)。`delete: true` は明示的な retract 用フラグで、storage 層の
  挙動は同じだが log 上の意図が異なる。
- 週内の `recommended_rank` 一意性は publish 時の invariant。衝突したら
  全 write 前に run を fail させるので、Firestore に rank=1 が同一週に
  2 件並ぶことはない。

## 4. デプロイトポロジー

```mermaid
graph TB
  subgraph GCP["GCP project: my-utilities-490202"]
    subgraph Region["Region: asia-northeast1"]
      Service["Cloud Run Service<br/>x402-cms<br/>min-instances=1"]
      Job1["Cloud Run Job<br/>x402-cms-indexer"]
      Job2["Cloud Run Job<br/>x402-cms-x-indexer"]
      Job3["Cloud Run Job<br/>x402-cms-issue-indexer"]
      Sched["Schedulers ×6<br/>Job ごとに週次・月 + 日次"]
    end

    subgraph SAs["Service Accounts"]
      Runner["x402-cms-runner<br/>(Firestore + Secret reader)"]
      Schler["x402-cms-scheduler<br/>(run.invoker +<br/>jobs.runWithOverrides)"]
    end

    subgraph SM["Secret Manager"]
      BS["x402-cms-x-bearer"]
      HS["x402-cms-tracked-handles"]
      TS["x402-cms-topics"]
    end

    FSdb[("Firestore<br/>4 collections")]
  end

  Sched -->|"oauth"| Job1
  Sched -->|"oauth"| Job2
  Sched -->|"oauth"| Job3

  Job1 --> FSdb
  Job2 --> FSdb
  Job3 --> FSdb
  Service --> FSdb

  BS -.->|"env var"| Job2
  HS -.->|"file mount"| Job2
  HS -.->|"file mount /secrets"| Service
  TS -.->|"file mount /topics"| Service

  Runner -.- Service
  Runner -.- Job1
  Runner -.- Job2
  Runner -.- Job3
  Schler -.- Sched
```

- **Service と Jobs の使い分け**。Service は常時起動 (`min-instances=1`、
  cold start を回避)。Jobs は短命 (X indexer は 10〜20 秒で完走)。各 Job
  は 2 本の schedule を持つ: 週次・月曜の run が先週を確定し、日次の run
  が `--current` の args override で進行中の週を更新する。
- **2 つの SA、権限は狭く**。`x402-cms-runner` は `datastore.user` +
  対象 3 secret への `secretAccessor` のみ。`x402-cms-scheduler` は対象
  3 Jobs への `run.invoker` に加え、最小のカスタムロール
  (`run.jobs.runWithOverrides`) を持つ — 日次 trigger が args override を
  渡すには素の invoker では足りないためである。
- **token と curated file で mount スタイルが違う**。`X_BEARER_TOKEN` は
  文字列なので env var として mount。curated yaml は file mount で、
  Cloud Run は 1 つの mount ディレクトリに 1 secret しか置けないため、
  handles は `/secrets/tracked_handles.yaml`、topics は
  `/topics/topics.yaml` に分かれる (loader のコードは local dev と
  同じまま、path だけが違う)。

## 5. モジュールマップ

```
code/
├── schemas/                  {pr, issue, x_post, commentary}.py · Pydantic
├── utils/
│   ├── dates.py              parse_iso_week, previous/current_iso_week,
│   │                         resolve_target_week, week_of, shift_iso_week
│   └── firestore.py          build_client (inject > project > ADC)
├── indexers/
│   ├── github_indexer.py     多種別 PR indexer (merged / active / new)
│   ├── github_issue_indexer.py  活発 issue の indexer (issues collection)
│   ├── x_text_parser.py      parse_pr_references
│   └── x_indexer/            (5 ファイル package)
│       ├── _http.py          API client + tweet → XPost 正規化
│       ├── loader.py         tracked_handles.yaml (flat / clusters 両対応)
│       ├── writer.py         x_posts upserter
│       ├── orchestrator.py   週単位の resolve → fetch → write
│       └── __main__.py       CLI
├── renderers/
│   └── digest/
│       ├── readers.py        5 つの Firestore reader (議論系は
│       │                     comments 数の多い順で返す)
│       ├── bundle.py         DigestBundle, cross-refs, recommendations,
│       │                     JP cluster filter
│       ├── topics.py         curated な scope/keyword → category 表引き
│       ├── html.py           render_html: glance ダッシュボード、
│       │                     折りたたみ、セクション nav + 週リンク
│       └── agent_json.py     render_agent_payload
├── publish/
│   ├── vault_parser.py       frontmatter 解析 + Commentary 構築
│   └── publisher.py          scan + validate + tombstone + upsert
├── survey/
│   └── surveyor.py           /x402-survey のバックエンド (Markdown 出力)
├── server/
│   ├── main.py               FastAPI app + ServerConfig + handler
│   └── static/               vendor した pico.classless.min.css (MIT)
├── dispatch.py               User-Agent で human / agent を振り分け
└── observability.py          構造化 JSON アクセスログ

scripts/
├── deploy.sh                 Service デプロイ (handles + topics を mount)
├── deploy_job.sh             github_indexer Job
├── deploy_issue_job.sh       issue_indexer Job
├── deploy_x_job.sh           x_indexer Job (bearer + handles を mount)
├── setup_sa.sh               runtime SA
├── setup_secrets.sh          bearer + handles + topics (idempotent)
├── setup_scheduler.sh        GitHub indexer の週次 Scheduler
├── setup_issue_scheduler.sh  issue indexer の週次 Scheduler
├── setup_x_scheduler.sh      X indexer の週次 Scheduler
├── setup_daily_schedulers.sh 日次 --current trigger + カスタムロール
├── check_no_attribution.sh   pre-commit ガード (メタ記述の検出)
├── check_semantic.py         pre-commit ガード (LLM 層)
└── dogfood_payment_loop.py   buyer 側 smoke (Base Sepolia)
```

Claude Code 用スキル 3 本は本リポジトリ外、`~/.claude/skills/` 配下:

| skill            | 役割                                                    |
|------------------|---------------------------------------------------------|
| `/x402-reindex`  | indexer の週中手動再走                                  |
| `/x402-survey`   | 週内データの retrieval + clustering、judgment は入れない |
| `/x402-publish`  | vault → Firestore commentary、rank 衝突を fail-fast      |

## 6. Public / Private の分離

```mermaid
graph TB
  subgraph PubOSS["Public (本リポジトリ、commit 済み)"]
    Code["code/ · scripts/ · tests/"]
    OSSCfg["config/*.example.yaml<br/>(handles, topics)"]
    OSSPrompt["prompts/*.example.md"]
    Infra["Dockerfile · pyproject.toml"]
  end

  subgraph Repo["Private (本リポジトリ、gitignored)"]
    RealHandles["config/tracked_handles.yaml<br/>(curated handles + clusters)"]
    RealTopics["config/topics.yaml<br/>(scope/keyword → category)"]
    RealPrompts["prompts/*.md"]
    Env[".env"]
  end

  subgraph NotesRepo["Private (別リポジトリ: shuhei0866/personal-notes)"]
    VaultPath["life_value_lab/.../my_vault/<br/>x402_digest/views/*.md"]
  end

  subgraph Runtime["Runtime (Secret Manager)"]
    SecBearer["x402-cms-x-bearer"]
    SecHandles["x402-cms-tracked-handles"]
    SecTopics["x402-cms-topics"]
  end

  RealHandles -.->|"scripts/setup_secrets.sh"| SecHandles
  RealTopics -.->|"scripts/setup_secrets.sh"| SecTopics
  Env -.->|"X_BEARER_TOKEN の値"| SecBearer
  VaultPath -.->|"/x402-publish"| Code
```

リポジトリは公開だが、curator の judgement レイヤは 3 つの private 面に
分かれている:

- **本リポジトリ内、gitignored**: curated handle list 本体、topic 対応表、
  working prompts、`.env`。commit 済みの `.example.yaml` / `.example.md`
  は、fresh clone が live X API に対して即座に動き topic 分布も描ける
  template を担う。
- **別リポジトリ**: vault。commentary draft と編集履歴はそこに住む。
- **Secret Manager**: 本番 X bearer token と 2 つの curated yaml。
  Service + Jobs が起動時に mount する。いずれの値も `--set-env-vars`
  には載せない (Cloud Audit Logs / Cloud Build log への漏洩を防ぐ)。
