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
        "sessions_hint_nav": "↑↓ navigate",
        "sessions_hint_select": "Enter select",
        "sessions_hint_quit": "q quit",
        "profiles_hint_nav": "← → profile   ↑↓ session",
        "profiles_hint_delete": "d delete profile",
        "profiles_hint_new": "n new profile",
        "profiles_hint_rename": "r rename",
        "new_profile_prompt": "Name for new profile:",
        "new_profile_placeholder": "e.g. work",
        "new_profile_hint": "each profile has its own isolated memory",
        "profiles_limit_reached": "profile limit reached (5 max)",
        "rename_profile_prompt": "New display name:",
        "sessions_continuing": "continuing",
        "session_today": "today",
        "session_yesterday": "yesterday",
        "session_days_ago": "{n}d ago",
        # -- Conversation UI --
        "thinking": "thinking...",
        "listening": "listening...",
        "saving_memory": "saving memory...",
        "session_label": "session",
        "chat_hint_end": "ctrl+d end",
        "chat_hint_history": "ctrl+o history",
        "chat_hint_voice": "ctrl+t voice",
        "chat_hint_sessions": "ctrl+b sessions",
        "chat_history_expand": "ctrl+o expand",
        "chat_history_collapse": "ctrl+o collapse",
        "saving_memory_skip": "ctrl+c skip",
        # -- Memory --
        "memory_context_query": "who is the user, what is happening in their life right now",
        # -- Programmer mode --
        "programmer_ready": "Programmer mode active — {mode}. Ready for your request.",
        "programmer_sanctum_missing": "Programmer mode requires a sanctum. Run: python main.py --init",
        "programmer_choose_mode": "Choose interaction mode — [v]oice or [t]ext: ",
        "programmer_session_end": "Programmer session ended.",
        "programmer_mode_invalid": "type 'v' for voice or 't' for text",
        "programmer_mode_switched": "Mode switched to {mode}.",
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
        "sessions_hint_nav": "↑↓ navegar",
        "sessions_hint_select": "Enter selecionar",
        "sessions_hint_quit": "q sair",
        "profiles_hint_nav": "← → perfil   ↑↓ sessão",
        "profiles_hint_delete": "d excluir perfil",
        "profiles_hint_new": "n novo perfil",
        "profiles_hint_rename": "r renomear",
        "new_profile_prompt": "Nome do novo perfil:",
        "new_profile_placeholder": "ex: trabalho",
        "new_profile_hint": "cada perfil tem sua própria memória isolada",
        "profiles_limit_reached": "limite de perfis atingido (máx 5)",
        "rename_profile_prompt": "Novo nome do perfil:",
        "sessions_continuing": "continuando",
        "session_today": "hoje",
        "session_yesterday": "ontem",
        "session_days_ago": "há {n} dias",
        # -- Conversation UI --
        "thinking": "pensando...",
        "listening": "ouvindo...",
        "saving_memory": "salvando memória...",
        "session_label": "sessão",
        "chat_hint_end": "ctrl+d encerrar",
        "chat_hint_history": "ctrl+o histórico",
        "chat_hint_voice": "ctrl+t voz",
        "chat_hint_sessions": "ctrl+b sessões",
        "chat_history_expand": "ctrl+o expandir",
        "chat_history_collapse": "ctrl+o recolher",
        "saving_memory_skip": "ctrl+c pular",
        # -- Memory --
        "memory_context_query": "quem é o usuário, o que está acontecendo na vida dele agora",
        # -- Programmer mode --
        "programmer_ready": "Programmer mode active — {mode}. Ready for your request.",
        "programmer_sanctum_missing": "Programmer mode requires a sanctum. Run: python main.py --init",
        "programmer_choose_mode": "Choose interaction mode — [v]oice or [t]ext: ",
        "programmer_session_end": "Programmer session ended.",
        "programmer_mode_invalid": "type 'v' for voice or 't' for text",
        "programmer_mode_switched": "Mode switched to {mode}.",
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
