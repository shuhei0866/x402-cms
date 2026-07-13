# Agent-friendly Advantage Benchmark R0

[English](agent-friendly-advantage-benchmark-r0.md)

## 1. ステータス

- **状態:** 実装方針として合意済み
- **最初の利用者:** Shuhei＋Codex
- **最初の前向き評価:** `2026-W29`
- **R0での本番変更:** なし

## 2. 目的

R0では、次の一つの問いを継続的に検証できるベンチマークを作る。

> x402週次digestから3件の有用な判断を作る作業において、有料のAgent表現は、
> 無料HTMLへ迂回する場合より総作業量を削減できるか。

Agent JSONを再設計する前にベンチマークを置く。現行JSONに経済的優位がないという
結果も、有効なR0成果である。R0はbaselineを測り、後続releaseが有料表現を
**agent-friendly** と呼ぶ根拠を作る。

## 3. プロダクト仮説

構造化データは、形式だけでなく意思決定タスク全体で優位性が残る場合に限り、HTML
よりエージェントに適している。有料経路が合理的になる条件は次の通り。

```text
endpoint価格＋構造化データの処理コスト
    ＜ HTML取得＋意味復元＋検証＋誤りリスク
```

toCサブスクリプションでは、モデル推論の限界費用がほぼゼロに見える一方、x402の
支払いは明示的に見える。そのためR0は二つの観点を分けて報告する。

1. **物理的資源指標** — token、経過時間、tool call、retry。
2. **金銭換算指標** — endpoint価格と、合理的に換算できる場合の保守的な削減価値。

Base Sepolia settlementはprotocol疎通の証明であり、実際の経済的選好の証明ではない。
表現の追加価値が測定されるまで、mainnet価格はスコープ外とする。

## 4. 固定する利用タスク

すべてのarmへ同じタスクを渡す。

> 今週のx402 digestから、Shuheiが注目すべき3件を選ぶ。各項目について、重要な
> 理由、根拠URL、具体的な次の行動を示し、重要な不確実性を明記する。

目標完了時間は **90秒以内** とする。

応答は次の論理schemaに従う。

```json
{
  "weekly_thesis": "string",
  "top_items": [
    {
      "id": "string",
      "reason": "string",
      "evidence_urls": ["https://..."],
      "recommended_action": "string"
    }
  ],
  "uncertainties": ["string"]
}
```

`top_items`は必ず3件とする。

## 5. 固定する個人コンテキスト

R0ではpersonalisationをクライアント側の責務とする。両armへ同じversionの関心profile
を渡し、batch-settlement、日本人contributor、acliとの接続、x402-cms自体など、
Shuheiの現在のx402活動を示す。

実profileはprivateなbenchmark inputとし、公開repositoryへcommitしない。公開用の
example profileを用意してもよいが、正式runで実profileの代わりに黙って使用しては
ならない。manifestにはprofileのversionまたはdigestだけを記録する。

## 6. 実験設計

表現の価値と決済transportのoverheadを混同しないため、R0を二つの実験に分ける。

### 6.1 実験A — 表現価値

目的は入力表現だけの効果を分離すること。

| Arm | 入力 |
|---|---|
| H | 人間向けHTML response bodyの生データ |
| J | 現行Agent JSON response body |

ルール:

- 両表現を同じeditionの一つの凍結source snapshotから作る。
- 同じCodex model、effort、system instruction、task prompt、個人コンテキストを使う。
- 各armは、もう一方を参照できない新規contextで実行する。
- Web検索と無関係な取得toolを禁止する。
- 渡された入力内にある事実とURLだけを使う。
- arm順をrandomizeし、seedを記録する。
- 実験Aの時間とcostには決済settlementを含めない。

### 6.2 実験B — E2Eエージェント経済性

目的はエージェントが実際に通る経路を測ること。

| Arm | 経路 |
|---|---|
| H | 無料browser/HTML経路によるlive digest request |
| J | live Agent request、HTTP 402、署名、settlement、有料JSON |

実験Bではdiscovery、fetch、settlement、parse、回答生成を一つのE2E runとして記録する。
記録対象は次の通り。

- HTTP request数とstatus遷移
- settlement networkと名目価格
- settlement latency、transaction identifier、retry、失敗
- 総経過時間とmodel使用量
- 実験Aと同じ品質指標

現在のUser-Agent判定はroutingでありsecurity boundaryではない。R0では、エージェントが
HTML経路を選ぶことを禁止しない。

## 7. Datasetと汚染防止

初期studyは5つの適格editionを使う。

- 過去dry run 4週。暫定対象は`2026-W24`〜`2026-W27`
- 前向きdogfood 1週。`2026-W29`

`2026-W28`は、評価者と現在のCodex contextがすでに内容を確認しているため正式採点から
除外する。

editionの適格条件は次の通り。

- HTMLとJSONがともに存在し、空ではない
- 両armのsource coverageが同等であると記録できる
- どちらのarmも実行する前にcaptureを凍結している
- 評価するCodex contextがedition内容を事前に見ていない

暫定対象週が不適格なら、最も近い過去の適格週に置き換え、置換を記録する。

## 8. Model制御

R0はCodexだけを使う。benchmarkが成立し、最初の利用者に対してJSONの優位が確認される
まで、複数modelへの一般化は行わない。

run manifestには次を記録する。

- model identifier
- effort level
- prompt version
- profile versionまたはdigest
- editionとsource snapshot digest
- armとrandomization seed
- 開始・完了時刻
- tool policy

両armでmodelまたはeffortが異なる比較は無効とする。

## 9. 指標

### 9.1 自動指標

- input/output token
- input byte
- wall-clock時間
- model/API callとtool call
- 実験BのHTTP requestと決済retry
- response schema妥当性
- 3件出力の妥当性
- 根拠URLが入力表現内に存在するか
- 推薦の重複数
- run failureとtimeout

生の指標を分けて保持し、任意の重みを使った単一scoreでtrade-offを隠さない。

### 9.2 人間によるブラインド評価

editionごとに二つの短い出力へ中立的なlabelを付け、HTML由来かJSON由来かを伏せて
順番をrandomizeする。

Shuheiは次を判定する。

- どちらが今週の重要点を適切に選んだか
- どちらが有用な次の行動を提示したか
- 重大な事実誤認または根拠不整合があるか
- 総合選好: 先の出力、後の出力、同等

個々のsource itemへの細かいlabel付けは求めない。「追う」「ノイズ」「返信する」
「調べる」「実装する」といった自然な反応を、別途downstream valueとして記録する。

## 10. Benchmark完成条件とプロダクトgate

再現可能な比較とブラインド評価packetを生成できればR0は完成とする。現行JSONが勝つ
必要はない。

後続のagent-friendly表現を経済性検証へ進める条件は、5 editionを通じて次を満たすこと。

1. 5回中4回以上、ブラインド比較でHTMLより悪くない
2. 重大な事実誤認または根拠不整合がない
3. 主要資源指標の少なくとも一つを中央値30%以上削減する
4. 明示的に受容したtrade-offなしに、他の主要資源指標を10%超悪化させない
5. 提案価格が、保守的に見積もった削減価値を十分に下回る

gate通過は価格・mainnet実験を許可するが、それらを義務付けない。

## 11. Artifactと結果の方針

Gitで追跡するもの:

- 本仕様書と英語正本
- benchmark codeと公開example input
- versioned promptとoutput schema
- run manifest schema
- 指標、判断、artifact digestだけを含む集計report

Gitで追跡しないもの:

- captureしたHTML/JSON body
- privateな関心profile
- modelのraw transcript
- 決済credential、wallet情報
- 未redactのrun artifact

生成物はgitignoreされたbenchmark artifact directoryに置く。集計reportからはdigestと、
必要な場合のみ外部artifact pointerで参照する。

## 12. 所有境界

`x402-cms`はdigest収集、rendering、benchmark capture、human/agent表現比較を担当する。

`x-402-contents-manager`は、将来の再利用可能なoffer、entitlement、feedback基盤の境界とする。
R0では依存を追加しない。

## 13. スコープ外

- 本番Agent JSON schemaの変更
- 無料HTMLの意図的な劣化・省略
- User-Agent偽装やHTML scrapingの防止
- server側の個人ranking
- benchmark用database
- 複数model評価
- Base mainnet移行
- 本番価格の決定
- batch-settlement統合

## 14. リリース順序

### R0-A — 表現benchmark harness

- versioned task prompt、private profile interface、output schema、run manifestを定義
- 一つのedition snapshotを凍結し、両armをrender
- 分離したCodex runを実行
- 自動指標を収集し、blind packetを生成

### R0-B — 過去baseline

- 適格な過去4 editionを実行
- HTMLまたはJSONが生む回避可能な作業を特定
- raw contentを含まない集計baselineを公開

### R0-C — 前向きdogfood

- review前に`2026-W29`を凍結
- ブラインド評価を完了
- どの推薦が実際の行動につながったかを記録
- 観測されたbottleneckから最小のR1変更を決める

### R1 — Agent decision packet

R1の詳細はR0の証拠が出るまで決めない。現時点の有力仮説は、stable ID、source coverage、
evidence link、entity relation、不確実性を持つdelta-first packetである。

## 15. R0受け入れ条件

- [ ] 一つのcommandで、適格な凍結editionのどちらのarmも実行できる
- [ ] 両armが同じmodel、effort、prompt、profile versionを使うことを保証する
- [ ] 各armを新規contextと定義済みtool policyで実行する
- [ ] 各runが有効なmanifestと固定shapeの結果を出力する
- [ ] composite scoreを使わず自動指標を収集する
- [ ] originを伏せ、順番をrandomizeした人間評価packetを生成できる
- [ ] 過去captureとmodel transcriptをgitignoreする
- [ ] 実験Aが決済overheadを除外する
- [ ] 実験Bが402 settlement経路全体を記録する
- [ ] `2026-W28`を正式採点へ含められない
- [ ] 既存test suiteがすべてgreenを維持する
