"""Human home, archive, and unpublished-edition pages."""

from __future__ import annotations

from html import escape

from code.renderers.digest.i18n import fmt_week_range, messages, normalize_lang
from code.renderers.digest.publication import PublishedEdition


def _lang_query(lang: str) -> str:
    return f"?lang={lang}"


def _document(title: str, body: str, lang: str, *, current_path: str) -> str:
    m = messages(lang)
    return f"""<!DOCTYPE html>
<html lang="{escape(m["html_lang"])}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<link rel="stylesheet" href="/static/pico.classless.min.css">
<link rel="stylesheet" href="/static/digest.css">
</head>
<body>
<main>
<header class="sitehead">
<a href="/{_lang_query(lang)}">x402-cms</a>
<nav>
<a href="/archive{_lang_query(lang)}">{escape(m["archive_title"])}</a>
<a href="{escape(current_path)}{_lang_query(m["toggle_to"])}">{escape(m["toggle_text"])}</a>
</nav>
</header>
{body}
</main>
</body>
</html>
"""


def _edition_list(editions: list[PublishedEdition], lang: str) -> str:
    m = messages(lang)
    if not editions:
        return f'<p class="empty">{escape(m["empty_editions"])}</p>'
    rows = "\n".join(
        '<li class="edition">'
        f'<a href="/digest/{escape(edition.week)}{_lang_query(lang)}">'
        f"<strong>{escape(edition.title)}</strong>"
        f"<span>{escape(fmt_week_range(edition.week, m))}</span>"
        f"<small>{escape(edition.week)}</small>"
        "</a></li>"
        for edition in editions
    )
    return f'<ol class="editions">\n{rows}\n</ol>'


def render_home(
    editions: list[PublishedEdition],
    lang: str = "en",
) -> str:
    """Render the latest published edition and recent archive rows."""
    lang = normalize_lang(lang)
    m = messages(lang)
    if not editions:
        body = (
            f'<p class="eyebrow">{escape(m["latest_edition"])}</p>'
            f"<h1>{escape(m['site_tagline'])}</h1>"
            f'<p class="empty">{escape(m["empty_editions"])}</p>'
        )
        return _document("x402-cms", body, lang, current_path="/")

    latest = editions[0]
    recent = editions[1:]
    recent_html = (
        f"<h2>{escape(m['recent_editions'])}</h2>{_edition_list(recent, lang)}"
        if recent
        else ""
    )
    body = (
        f'<p class="eyebrow">{escape(m["latest_edition"])}</p>'
        f'<h1><a href="/digest/{escape(latest.week)}{_lang_query(lang)}">'
        f"{escape(latest.title)}</a></h1>"
        f'<p class="editionmeta">{escape(fmt_week_range(latest.week, m))} · '
        f'<span class="weekcode">{escape(latest.week)}</span></p>'
        f"{recent_html}"
    )
    return _document("x402-cms", body, lang, current_path="/")


def render_archive(
    editions: list[PublishedEdition],
    lang: str = "en",
) -> str:
    """Render all editorially published editions newest first."""
    lang = normalize_lang(lang)
    m = messages(lang)
    body = f"<h1>{escape(m['archive_title'])}</h1>{_edition_list(editions, lang)}"
    return _document(
        f"x402-cms — {m['archive_title']}",
        body,
        lang,
        current_path="/archive",
    )


def render_not_found(
    week: str,
    editions: list[PublishedEdition],
    lang: str = "en",
) -> str:
    """Render a useful human 404 for a week with no content."""
    lang = normalize_lang(lang)
    m = messages(lang)
    latest = editions[0] if editions else None
    latest_link = (
        f'<a href="/digest/{escape(latest.week)}{_lang_query(lang)}">'
        f"{escape(m['latest_link'])}</a> · "
        if latest
        else ""
    )
    body = (
        f'<p class="eyebrow">404 · {escape(week)}</p>'
        f"<h1>{escape(m['edition_not_found'])}</h1>"
        f'<p>{latest_link}<a href="/archive{_lang_query(lang)}">'
        f"{escape(m['archive_link'])}</a></p>"
    )
    return _document(
        f"404 — {week}",
        body,
        lang,
        current_path=f"/digest/{week}",
    )
