"""Message catalog for the human HTML view.

Only the chrome is localised — section names, glance labels, the nav,
snapshot, meta words, empty states, dates. The rows themselves (PR /
issue titles, tweet text, handles) are upstream source data and stay
in their original language; machine-translating them would distort the
record the digest exists to keep.

`messages(lang)` returns a flat dict merged over English, so any key
missing from a locale falls back to the English string rather than a
KeyError. English values are the exact strings the renderer emitted
before i18n, so the default output is byte-identical.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from code.utils.dates import parse_iso_week

SUPPORTED = ("en", "ja")

# Fixed English month abbreviations. `strftime("%b")` follows the
# process LC_TIME, so a non-English runtime locale would leak localised
# month names into the English view; this table keeps it deterministic.
_EN_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

_EN: dict[str, str] = {
    "lang": "en",
    "html_lang": "en",
    "nav_aria": "sections",
    "digest_word": "digest",
    "archive_title": "Archive",
    "archive_link": "View archive",
    "latest_edition": "Latest edition",
    "latest_link": "Read the latest edition",
    "recent_editions": "Recent editions",
    "site_tagline": "x402 changes, edited for implementation decisions",
    "empty_editions": "No published editions yet.",
    "edition_not_found": "This edition is not published.",
    # language toggle: text shown, and the lang it links to
    "toggle_text": "日本語",
    "toggle_to": "ja",
    # section names (also the collapsed summaries)
    "sec_picks": "Picks",
    "sec_active": "Active discussions",
    "sec_issues": "Issues",
    "sec_merged": "Merged PRs",
    "sec_new": "Newly opened",
    "sec_xposts": "X posts",
    "sec_japan": "Japan community",
    "sec_cross": "Cross-references",
    "sec_commentary": "Commentary",
    # nav short labels
    "nav_glance": "Glance",
    "nav_picks": "Picks",
    "nav_active": "Active",
    "nav_issues": "Issues",
    "nav_merged": "Merged",
    "nav_new": "New",
    "nav_xposts": "X posts",
    "nav_japan": "Japan",
    "nav_cross": "Cross-refs",
    "nav_commentary": "Commentary",
    # glance
    "glance_title": "This week at a glance",
    "glance_who": "Who moved",
    "glance_hot": "What's hot",
    "glance_talk": "Where the talk is",
    "glance_gh_topics": "GitHub topics",
    "glance_x_clusters": "X clusters — top-level (+replies)",
    "topic_uncategorised": "uncategorised",
    "x_movers_prefix": "X:",
    "x_keywords_prefix": "X keywords:",
    "empty_gh_activity": "No GitHub activity this week.",
    "empty_hot": "No live discussions this week.",
    "topics_unavailable": (
        "No topics config loaded — GitHub topic distribution unavailable."
    ),
    # snapshot labels
    "snap_merged": "merged",
    "snap_active": "active",
    "snap_new": "newly opened",
    "snap_issues": "issues",
    "snap_xposts": "X posts",
    "snap_replies": "+ {n} replies",
    # parametrised fragments
    "bot_foot": "{n} bot account(s) · {items} item(s) · folded",
    "fold_replies": "Replies from @{handle} ({n})",
    "fold_closed": "Closed without merge ({n})",
    "cross_item": "{ref} — mentioned by X post id(s): {ids}",
    # meta / state words
    "state_open": "open",
    "state_closed": "closed",
    "state_draft": "draft",
    "state_merged": "merged",
    "tag_merged": "merged",
    "tag_new": "new",
    "when_updated": "updated {d}",
    "when_opened": "opened {d}",
    "when_merged": "merged {d}",
    "when_active": "active",
    "when_new": "new",
    # empty states
    "empty_active": "No active discussions this week.",
    "empty_issues": "No active issues this week.",
    "empty_merged": "No merged PRs this week.",
    "empty_new": "No newly opened PRs this week.",
    "empty_new_open": "No still-open PRs this week.",
    "empty_xposts": "No X posts this week.",
    "empty_toplevel": "No top-level posts this week.",
    "empty_japan": "No Japan community posts this week.",
    "empty_cross": "No cross-references this week.",
    "empty_picks": "No picks this week.",
    "empty_commentary": "No additional commentary this week.",
}

_JA: dict[str, str] = {
    "lang": "ja",
    "html_lang": "ja",
    "nav_aria": "セクション",
    "digest_word": "ダイジェスト",
    "archive_title": "記事一覧",
    "archive_link": "記事一覧へ",
    "latest_edition": "最新号",
    "latest_link": "最新号を読む",
    "recent_editions": "最近の記事",
    "site_tagline": "x402の変化を、実装の論点に変える",
    "empty_editions": "公開済みの記事はまだありません。",
    "edition_not_found": "この週の記事は公開していません。",
    "toggle_text": "English",
    "toggle_to": "en",
    "sec_picks": "ピック",
    "sec_active": "アクティブな議論",
    "sec_issues": "Issue",
    "sec_merged": "マージ済み PR",
    "sec_new": "新規オープン",
    "sec_xposts": "X 投稿",
    "sec_japan": "日本コミュニティ",
    "sec_cross": "相互参照",
    "sec_commentary": "コメンタリ",
    "nav_glance": "概要",
    "nav_picks": "ピック",
    "nav_active": "アクティブ",
    "nav_issues": "Issue",
    "nav_merged": "マージ",
    "nav_new": "新規",
    "nav_xposts": "X",
    "nav_japan": "日本",
    "nav_cross": "相互参照",
    "nav_commentary": "コメンタリ",
    "glance_title": "今週のまとめ",
    "glance_who": "動いた人",
    "glance_hot": "注目の議論",
    "glance_talk": "話題の在りか",
    "glance_gh_topics": "GitHub トピック",
    "glance_x_clusters": "X クラスタ — 本投稿（+返信）",
    "topic_uncategorised": "未分類",
    "x_movers_prefix": "X:",
    "x_keywords_prefix": "X キーワード:",
    "empty_gh_activity": "今週の GitHub 活動はありません。",
    "empty_hot": "今週の活発な議論はありません。",
    "topics_unavailable": (
        "topics 設定が読み込まれていないため、GitHub トピックの分布を表示できません。"
    ),
    "snap_merged": "マージ",
    "snap_active": "アクティブ",
    "snap_new": "新規",
    "snap_issues": "Issue",
    "snap_xposts": "X 投稿",
    "snap_replies": "+ 返信 {n}",
    "bot_foot": "bot {n} アカウント · {items} 項目 · 折りたたみ",
    "fold_replies": "@{handle} の返信（{n}）",
    "fold_closed": "マージされず終了（{n}）",
    "cross_item": "{ref} — 言及した X 投稿 id: {ids}",
    "state_open": "オープン",
    "state_closed": "クローズ",
    "state_draft": "ドラフト",
    "state_merged": "マージ済み",
    "tag_merged": "マージ",
    "tag_new": "新規",
    "when_updated": "更新 {d}",
    "when_opened": "作成 {d}",
    "when_merged": "マージ {d}",
    "when_active": "アクティブ",
    "when_new": "新規",
    "empty_active": "今週のアクティブな議論はありません。",
    "empty_issues": "今週のアクティブな Issue はありません。",
    "empty_merged": "今週のマージ済み PR はありません。",
    "empty_new": "今週の新規 PR はありません。",
    "empty_new_open": "今週のオープン中の PR はありません。",
    "empty_xposts": "今週の X 投稿はありません。",
    "empty_toplevel": "今週の本投稿はありません。",
    "empty_japan": "今週の日本コミュニティの投稿はありません。",
    "empty_cross": "今週の相互参照はありません。",
    "empty_picks": "今週のピックはありません。",
    "empty_commentary": "追加のコメンタリはありません。",
}

_LOCALES: dict[str, dict[str, str]] = {"en": _EN, "ja": _JA}


def normalize_lang(raw: str | None) -> str:
    """Map an arbitrary lang token to a supported locale (default en)."""
    return "ja" if (raw or "").strip().lower().startswith("ja") else "en"


def lang_from_accept_language(header: str | None) -> str:
    """Pick a locale from an Accept-Language header (primary tag wins).

    A crude but predictable rule: the browser's first (most-preferred)
    language tag decides. `ja` / `ja-JP` → Japanese; anything else,
    including an empty header, falls back to English.
    """
    primary = (header or "").split(",")[0].strip()
    return normalize_lang(primary)


def messages(lang: str) -> dict[str, str]:
    """Locale strings merged over English, so misses fall back to en."""
    return {**_EN, **_LOCALES.get(lang, {})}


def fmt_date(dt: datetime, m: dict[str, str]) -> str:
    """`Jul 4` (en) / `7月4日` (ja).

    Built by hand rather than `strftime` — `%-d` is not portable and
    `%b` follows the process locale, either of which could distort the
    date; the fixed month table keeps English deterministic.
    """
    if m["lang"] == "ja":
        return f"{dt.month}月{dt.day}日"
    return f"{_EN_MONTHS[dt.month - 1]} {dt.day}"


def fmt_week_range(week: str, m: dict[str, str]) -> str:
    """Human calendar range for an ISO week label."""
    start, end_exclusive = parse_iso_week(week)
    end = end_exclusive - timedelta(days=1)
    if m["lang"] == "ja":
        if start.year == end.year:
            return (
                f"{start.year}年{start.month}月{start.day}日〜{end.month}月{end.day}日"
            )
        return f"{start.year}年{start.month}月{start.day}日〜{end.year}年{end.month}月{end.day}日"
    if start.year == end.year and start.month == end.month:
        return f"{_EN_MONTHS[start.month - 1]} {start.day}–{end.day}, {start.year}"
    if start.year == end.year:
        return (
            f"{_EN_MONTHS[start.month - 1]} {start.day}–"
            f"{_EN_MONTHS[end.month - 1]} {end.day}, {start.year}"
        )
    return (
        f"{_EN_MONTHS[start.month - 1]} {start.day}, {start.year}–"
        f"{_EN_MONTHS[end.month - 1]} {end.day}, {end.year}"
    )


def state_word(state: str, m: dict[str, str]) -> str:
    """Localise a GitHub state token; pass unknown values through."""
    return m.get(f"state_{state}", state)
