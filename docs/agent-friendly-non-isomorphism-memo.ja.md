# 設計メモ: 意味的一貫性と機能的非同型性

[English](agent-friendly-non-isomorphism-memo.md)

- **日付:** 2026-07-19
- **状態:** R1の方向性として採用。schemaと本番変更は未承認
- **対象:** 無料の人間向けHTMLと、将来の有料Agent projectionの関係

## 判断

人間向けHTMLとAgent表現は、正しい共通のevidence substrateを共有しつつ、機能的には同型であり続けるべきではない。

設計目標は次の通り。

> 意味的一貫性を保ち、機能的な非同型性を許す。

人間向けprojectionの主な役割は、人間が状況を認知し、何が重要かを判断し、どこへ意思を向けるかを選べるようにすることにある。Agent projectionの役割は、委任されたAgentが探索、分解、実行、検証、報告を進められるようにすることにある。人間向け記事をJSONへ直列化しただけのものはAI capableではあるが、まだ強いAgent productではない。

R0は、現在の同型性が高い設計のbaselineとして維持する。このメモはR0のinput、採点、受け入れ条件を変更しない。baselineの後に検証する方向を記録する。

## なぜ判断が変わったか

W27のblind reviewでは、HTML由来とJSON由来の回答はどちらも妥当だった。一方、どちらも、取り上げたprotocol workが`x402-foundation/x402`の外で起きている問題と接地しているかを判断できなかった。追加のexternal-groundingでは、次の4層を新たに再構成する必要があった。

1. 問題が実在する証拠
2. 提案されたmechanismが改善する証拠
3. 独立した採用・利用の証拠
4. 反証と限界

追加価値の大半を作ったのはJSON parsingではなく、この再構成だった。その過程で、物語的なprojectionだけでは実行可能な形になっていなかった因果関係も修正された。deploymentはadoptionではなかった。Bazaar response headerの欠落は単一原因ではなかった。receipt bindingは想定より強い外部conformanceを持つ一方、security上の対象範囲は限定的だった。

したがって、有料表現はこの再構成作業を減らす必要がある。そうでなければ、Agentは無料HTMLからほぼ同じ意味を復元し、有料経路を避ける方が合理的になる。

## Principal–agentとしての解釈

AIのagencyは関係的に決まる。人間のprincipalがintent、constraint、authorityを与え、AIがそれを実現するagentになる。そのAIが仕事を分解して別のagentへ委任するとき、人間に対してagentでありながら、下位に対しては局所的なprincipalになる。

```text
人間のprincipal
  ↓ intent、scope、authority、budget
agent / 局所的principal
  ↓ bounded task、authority、budget、success criteria
subagentまたは有料capability
  ↑ result、evidence、cost、receipt、unresolved state
agent
  ↑ 統合した結果とescalation
人間のprincipal
```

mandateは委任graphを下向きに流れ、result、evidence、receiptは上向きに戻る。したがってAgent projectionは、単にmachine-readableなのではなく、delegation-readyであるべきである。

## 各projectionの役割

| 面 | 主な役割 | 答えるべき問い |
|---|---|---|
| 人間向けHTML | 認知、方向づけ、優先順位 | 何が起きたか。なぜ重要か。何へ注意を向けるか |
| Agent discovery metadata | 支払い前のcapability選択 | 何ができるか。価格はいくらか。input、output、network、proofは何か |
| 有料Agent work packet | 探索と実行 | 何が裏付けられているか。何が未確定か。どの権限で次に何を行い、どう成功を検証するか |
| Receipt / result | 上位へのaccountability | 何を試し、何が起き、いくら使い、principalが何を検証できるか |

無料HTMLを意図的に劣化させてはならない。有料packetは、人間の基本的理解を隠すことではなく、再構成コストの高い構造と証拠を提供することで価格を正当化する。

## 共通substrateと非対称なprojection

両projectionはstable IDを持つ共通のevidence substrateから生成する。ただし、選択と配置は異なってよい。

共通substrateは、将来的に少なくとも次を表現できる必要がある。

- claimとstable claim ID
- source observationとtimestamp
- supporting evidenceとcounterevidence
- evidenceの独立性とprovenance
- confidenceとunresolved question
- actor、proposal、implementation、deployment間のrelation

人間向けprojectionは、これをeditorial rhythmへ圧縮できる。Agent projectionは、検証と実行に必要なjoinを保持できる。同じ事実がprojection間で黙って変わってはならないが、operational detailの量まで揃える必要はない。

## R1 work packetの候補

R1は記事schemaの拡張ではなく、delegation-readyなwork packetとして探索する。

```json
{
  "edition": "2026-W27",
  "thesis": "string",
  "claims": [
    {
      "id": "claim:batch-demand",
      "assertion": "string",
      "status": "supported | contested | unknown",
      "importance": "string",
      "supporting_evidence": [],
      "counterevidence": [],
      "unknowns": [],
      "observed_at": "RFC3339 timestamp"
    }
  ],
  "work_items": [
    {
      "id": "work:onchain-adoption-probe",
      "objective": "string",
      "claim_ids": ["claim:batch-demand"],
      "required_authority": "read_only",
      "estimated_cost": {},
      "preconditions": [],
      "stop_conditions": [],
      "success_criteria": [],
      "verification": [],
      "escalate_when": []
    }
  ],
  "expected_receipt": {
    "result": "required",
    "evidence": "required",
    "cost": "required",
    "unresolved_state": "required"
  }
}
```

これは本番schemaではなく仮説である。packetはserver-sideのpersonal rankingを持たず、ユーザーに代わってauthorityを与えない。client-side principalが承認できる、boundedでverifiableなworkを提示する。

## 経済条件

有料経路が合理的になるのは、次の条件を満たす場合だけである。

```text
endpoint価格 + packet処理コスト
  < HTML取得 + 再構成 + 検証 + 誤りリスク
```

したがって差別化は、削減できた仕事として測る。claimとevidenceのjoin、counterevidence、freshness、独立採用の分類、実行可能なprobe、stop condition、expected receiptなどが、削減源の候補になる。

capabilityと価格のmetadataは、支払い前に無料で発見可能であるべきである。Agentはpacketを盲目的に購入せず、関連性と価格を先に判断できなければならない。

## 次の実験: 手作業のgolden packetを1件作る

まだ本番schemaを実装しない。まず既存のexternal-groundingを材料に、意図的に非同型なW27 golden packetを1件だけ手作業で作る。

同じmodel、tool、authority、taskの下で、次の2経路をE2E比較する。

| Arm | 開始面 |
|---|---|
| H | 現在のhuman-first W27 HTML相当brief |
| W | W27のdelegation-ready golden work packet |

R0の表現比較ではなく、次のproduct taskを使う。

> W27の3テーマのうち、x402-cmsが次に行動すべきものを決める。observed problemとsolution adoptionを区別し、必要なauthorityとcostを示し、検証可能なsuccess conditionとstop conditionを持つbounded execution planを1件作る。

R0-Aと異なり、両armでWebを許可する。external retrievalは、削減対象となる仕事の一部だからである。

記録するもの:

- wall-clock、token、Web/tool call、retry
- unsupportedまたは過剰なcausal claim
- deploymentとadoptionを区別できたか
- supporting evidenceとcounterevidenceを両方持つか
- actionがauthority、precondition、cost、success、stop、verification、escalationを持つか
- 別のAgentがhuman briefを読み直さずにplanを実行できるか

work-packet armがjudgmentとevidence qualityを落とさず、再構成作業を減らせれば成功とする。1 editionで判断できるのはschema spikeへ進む価値があるかまでで、価格設定やmainnet承認ではない。

## 帰結

golden packetが有用だった場合:

1. 最小のevidence substrateとstable IDを定義する
2. versioned R1 packet schemaを定義する
3. 共通substrateからrendererを追加する
4. 有料capabilityの無料discovery metadataを公開する
5. 本番化やmainnet変更前に、複数editionで経済性benchmarkを再実行する

有用でなければR0を維持し、JSONをAgentらしく見せるためだけにschema complexityを増やさない。

## Non-goals

- 人間向けHTMLを劣化させること
- 全source materialを有料化すること
- JSON syntax自体をAgent価値とみなすこと
- serverがユーザーに代わってauthorityを与えること
- incoming mandateより広い権限をsubagentへ渡すこと
- work packetやreceiptが全てのpayment、delivery、accountability failureを解くと主張すること
- この実験で本番routing、価格、settlement scheme、mainnet statusを変更すること
