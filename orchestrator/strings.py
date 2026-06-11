"""
strings.py — user-facing string catalog (UI + communication layer).

All text shown to the user as interface or conversation belongs here.
Operational logs and technical errors do NOT go here — see output.py and errors.py.

Locale is hardcoded for now. When i18n is needed:
  1. Add a new locale key to _STRINGS
  2. Set _LOCALE from env/config — call sites don't change.

Categories:
  ui    — chrome, banners, setup messages, output prefixes
  comm  — conversational labels and greetings (part of the YANA experience)
"""

from __future__ import annotations

_LOCALE = "pt_BR"

_STRINGS: dict[str, dict[str, str]] = {
    "pt_BR": {
        # -- UI --
        "banner":          "--- YANA (Ctrl+C para sair) ---",
        "sanctum_missing": "Sanctum não encontrado.",
        "warn_prefix":     "aviso",
        "error_prefix":    "erro",
        # -- Communication --
        "user_label":      "Você",
        "greeting":        "Oi, estou ouvindo.",
    },
}


def t(key: str, **kwargs: object) -> str:
    """
    Look up a user-facing string by key for the active locale.

    Usage:
        print(t("banner"))
        print(t("sanctum_missing"))
        input(f"{t('user_label')}: ")
    """
    locale_strings = _STRINGS.get(_LOCALE, _STRINGS["pt_BR"])
    text = locale_strings.get(key, f"[missing string: {key}]")
    return text.format(**kwargs) if kwargs else text
