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

_LOCALE = "en"

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # -- UI --
        "banner": "--- YANA (Ctrl+C to quit) ---",
        "sanctum_missing": "Sanctum not found.",
        "warn_prefix": "warn",
        "error_prefix": "error",
        # -- Communication --
        "user_label": "You",
        # -- Session browser --
        "sessions_new": "new session",
        "sessions_hint": "↑↓ navigate   Enter select   q quit",
        "sessions_continuing": "continuing",
        "session_today": "today",
        "session_yesterday": "yesterday",
        "session_days_ago": "{n}d ago",
        # -- Conversation UI --
        "thinking": "thinking...",
        "listening": "listening...",
        "saving_memory": "saving memory...",
        "session_label": "session",
        # -- Programmer mode --
        "programmer_ready": "Programmer mode active — {mode}. Ready for your request.",
        "programmer_sanctum_missing": "Programmer mode requires a sanctum. Run: python main.py --init",
        "programmer_choose_mode": "Choose interaction mode — [v]oice or [t]ext: ",
        "programmer_session_end": "Programmer session ended.",
    },
    "pt_BR": {
        # -- UI --
        "banner": "--- YANA (Ctrl+C para sair) ---",
        "sanctum_missing": "Sanctum não encontrado.",
        "warn_prefix": "aviso",
        "error_prefix": "erro",
        # -- Communication --
        "user_label": "Você",
        # -- Session browser --
        "sessions_new": "nova sessão",
        "sessions_hint": "↑↓ navegar   Enter selecionar   q sair",
        "sessions_continuing": "continuando",
        "session_today": "hoje",
        "session_yesterday": "ontem",
        "session_days_ago": "há {n} dias",
        # -- Conversation UI --
        "thinking": "pensando...",
        "listening": "ouvindo...",
        "saving_memory": "salvando memória...",
        "session_label": "sessão",
        # -- Programmer mode --
        "programmer_ready": "Programmer mode active — {mode}. Ready for your request.",
        "programmer_sanctum_missing": "Programmer mode requires a sanctum. Run: python main.py --init",
        "programmer_choose_mode": "Choose interaction mode — [v]oice or [t]ext: ",
        "programmer_session_end": "Programmer session ended.",
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
