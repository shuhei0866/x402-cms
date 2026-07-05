"""Tests for the digest chrome localisation.

The catalog localises only the scaffolding; `messages(lang)` merges
over English so a missing key falls back rather than raising. Locale
selection is a pure function of the query param / Accept-Language, so
it is tested without standing up the server.
"""

from __future__ import annotations

from datetime import datetime, timezone

from code.renderers.digest.i18n import (
    SUPPORTED,
    fmt_date,
    lang_from_accept_language,
    messages,
    normalize_lang,
    state_word,
)


class TestNormalizeLang:
    def test_ja_variants_map_to_ja(self) -> None:
        assert normalize_lang("ja") == "ja"
        assert normalize_lang("ja-JP") == "ja"
        assert normalize_lang("JA") == "ja"

    def test_everything_else_falls_back_to_en(self) -> None:
        assert normalize_lang("en") == "en"
        assert normalize_lang("fr") == "en"
        assert normalize_lang("") == "en"
        assert normalize_lang(None) == "en"


class TestLangFromAcceptLanguage:
    def test_primary_tag_decides(self) -> None:
        assert lang_from_accept_language("ja,en-US;q=0.9,en;q=0.8") == "ja"
        assert lang_from_accept_language("en-US,en;q=0.9,ja;q=0.8") == "en"

    def test_empty_or_missing_is_english(self) -> None:
        assert lang_from_accept_language("") == "en"
        assert lang_from_accept_language(None) == "en"


class TestMessages:
    def test_supported_locales_are_en_and_ja(self) -> None:
        assert SUPPORTED == ("en", "ja")

    def test_ja_localises_a_section_name(self) -> None:
        assert messages("ja")["sec_active"] == "アクティブな議論"
        assert messages("en")["sec_active"] == "Active discussions"

    def test_unknown_locale_is_english(self) -> None:
        assert messages("fr")["sec_active"] == "Active discussions"

    def test_missing_key_falls_back_to_english(self) -> None:
        # Every en key resolves in ja too (merged over en), so a locale
        # that omits a key never raises — it shows the English string.
        en = messages("en")
        ja = messages("ja")
        assert set(en).issubset(set(ja))


class TestFmtDateAndState:
    def test_date_format_per_locale(self) -> None:
        dt = datetime(2026, 7, 4, tzinfo=timezone.utc)
        assert fmt_date(dt, messages("en")) == "Jul 4"
        assert fmt_date(dt, messages("ja")) == "7月4日"

    def test_english_months_are_locale_independent(self) -> None:
        # Fixed table, not strftime("%b") — so a non-English process
        # locale can't leak a translated month into the English view.
        en = messages("en")
        assert fmt_date(datetime(2026, 1, 1, tzinfo=timezone.utc), en) == "Jan 1"
        assert fmt_date(datetime(2026, 12, 31, tzinfo=timezone.utc), en) == "Dec 31"

    def test_state_word_localises_known_and_passes_unknown(self) -> None:
        ja = messages("ja")
        assert state_word("open", ja) == "オープン"
        assert state_word("closed", ja) == "クローズ"
        # An unrecognised state token passes through untouched.
        assert state_word("weird", ja) == "weird"
