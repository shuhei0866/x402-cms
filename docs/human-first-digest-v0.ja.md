# Human-first Digest v0

## 目的

有料Agent projectionを拡張する前に、週次digestを日本向けx402メディアとして
読める状態にする。今回の対象は発見と閲覧であり、決済settlementとAgent JSON
schemaは変更しない。

## プロダクト境界

- `x402-cms`は収集、編集判断、公開、human/agent projectionを担当する。
- `x-402-contents-manager`は将来のoffer、決済、entitlement、feedback境界とする。
- User-Agent判定は経路の振り分けであり、情報秘匿の境界として扱わない。

## 公開ルール

公開済みのweek-level commentaryを、v0における編集版の公開記録とする。
per-item noteは記事を補強するが、それだけでは週を公開しない。同じweekに複数の
week-level commentaryが公開される場合、publishを失敗させる。

既存互換のため、raw sourceを持つdigestへの直接アクセスは維持する。トップ、
記事一覧、生成される前後リンクには、編集判断を経て公開された週だけを出す。

## 人間向け体験

- browserで`/`へアクセスすると、最新号と最近の記事を表示する。
- `/archive`は公開済み記事を新しい順に一覧表示する。
- `/digest/{week}`は編集タイトルと日付範囲を主表示し、ISO weekは補助情報にする。
- 前後移動は実際の公開記事をたどり、空weekを飛ばす。
- 完全に空のweekは人間向け404を返し、最新号と記事一覧へ案内する。Agent側の
  課金挙動は今回変更しない。

## 編集トーン

親しさや強い断定ではなく、切り口からattentionを生む。見出しは結論より、
残っている論点を示す。本文は「観測、意味、示唆」で整理し、宣伝的な文章より
一文早く終える。

本番promptはprivate layerに置き、公開repoには一般化したexampleとreview
checklistだけを置く。

## 受け入れ条件

- 公開記事が単一の公開ルールから導かれる。
- ISO weekを知らなくても日付を把握できる。
- 公開されていないweekへnavigationが生成されない。
- 公開記事が0件、1件、複数件の場合を扱える。
- 既存digest section、localisation、Agent JSON、settlementを壊さない。
- 公開記録の一意性、並び順、gap navigation、日付表示、empty stateをtestする。

## デプロイ前提

本番のsource weekとweek-level commentaryを照合する。トップまたは記事一覧へ
載せるweekには、公開済みweek-level commentaryを必ず1件用意する。raw dataが
存在するだけのweekを自動で公開扱いにはしない。

## スコープ外

- immutableな`DigestRevision`と`PublicationManifest v0`
- Agent JSON schema変更
- entitlementと価格方針
- mainnet移行
- 検索、SEO、WYSIWYG editor
