"""
connectors/garmin.py — GarminActivity connector.

Uses the garminconnect library (garth-based) for Garmin Connect API access.
Tokens are saved after first login so subsequent runs need no credentials prompt.

Setup:
  1. Create a credentials file (NOT in the repo) e.g. ~/.yana/credentials/garmin_fred.json:
       {"email": "fred@example.com", "password": "secret"}

  2. Reference it in orchestrator/config/connectors.yaml:
       config:
         credentials_file: "~/.yana/credentials/garmin_fred.json"
         token_dir: "~/.yana/tokens/garmin_fred"

  On first call the connector logs in and saves garth tokens to token_dir.
  Subsequent calls load the saved tokens (auto-refreshed by garth when expired)
  — no password needed after that.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from connectors import Connector, command, event, query


def _read_password(prompt: str) -> str:
    """Read a password from the terminal with echo suppressed.

    Uses msvcrt on Windows (getpass doesn't suppress echo in PowerShell/cmd),
    falls back to getpass on other platforms.
    """
    import sys

    print(prompt, end="", flush=True)

    if sys.platform == "win32":
        import msvcrt

        chars: list[str] = []
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                break
            if ch == "\x03":  # Ctrl+C
                print()
                raise KeyboardInterrupt
            if ch == "\x08":  # backspace
                if chars:
                    chars.pop()
                    print("\b \b", end="", flush=True)
            else:
                chars.append(ch)
                print("*", end="", flush=True)
        print()
        return "".join(chars)

    import getpass

    # getpass handles echo suppression on Unix/macOS
    password = getpass.getpass("")
    return password


class GarminActivityConnector(Connector):
    connector_description = "Health and activity data via Garmin — steps, sleep, stress, runs"

    def __init__(
        self,
        credentials_file: str | None = None,
        token_dir: str | None = None,
    ) -> None:
        self._credentials_file = Path(
            credentials_file or "~/.yana/credentials/garmin.json"
        ).expanduser()
        self._token_dir = Path(token_dir or "~/.yana/tokens/garmin").expanduser()
        self._client = None  # lazy

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @query(
        description="Steps taken today",
        returns={"type": "number", "unit": "steps/day"},
    )
    def steps_today(self) -> int:
        # _stats_today propagates auth/network errors; missing field → 0 is valid data
        stats = self._stats_today()
        return int(stats.get("totalSteps") or 0)

    @query(
        description="Calories burned today (active + resting)",
        returns={"type": "number", "unit": "kcal"},
    )
    def calories_today(self) -> int:
        stats = self._stats_today()
        return int(stats.get("totalKilocalories") or stats.get("activeKilocalories") or 0)

    @query(
        description="Average stress level today (0-100). Returns -1 if no data yet.",
        returns={"type": "number", "unit": "stress_score"},
    )
    def stress_level(self) -> int:
        data = self._svc().get_stress_data(date.today().isoformat())
        return int(data.get("avgStressLevel", -1) or -1)

    @query(
        description="Last night's sleep summary",
        returns={"type": "object"},
    )
    def last_sleep(self) -> dict:
        raw = self._svc().get_sleep_data(date.today().isoformat())
        dto = raw.get("dailySleepDTO") or raw
        return self._format_sleep(dto)

    @query(
        description="Most recent recorded physical activity",
        returns={"type": "object"},
    )
    def last_activity(self) -> dict:
        activities = self._svc().get_activities(0, 1)
        return self._format_activity(activities[0]) if activities else {}

    @query(
        description="Heart rate readings over the last N hours (default 24)",
        params={"hours": {"type": "number", "required": False}},
        returns={"type": "list"},
    )
    def heart_rate_history(self, hours: int = 24) -> list:
        data = self._svc().get_heart_rates(date.today().isoformat())
        readings = data.get("heartRateValues") or []
        if hours < 24:
            cutoff_ms = int((datetime.now(UTC) - timedelta(hours=hours)).timestamp() * 1000)
            readings = [r for r in readings if r and r[0] and r[0] >= cutoff_ms]
        return [
            {"timestamp_ms": r[0], "bpm": r[1]}
            for r in readings
            if r and len(r) >= 2 and r[1] is not None
        ]

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @command(
        description="Force a data refresh (drops cached client and reconnects)",
        returns={"type": "boolean"},
    )
    def sync(self) -> bool:
        self._client = None  # drop cache — next call rebuilds from fresh token
        self._svc()  # validate reconnect
        return True

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    _POLL_INTERVAL = 120  # seconds between activity polls

    @event(
        description="New physical activity recorded on the device",
        schema={"type": "object"},
    )
    def on_new_activity(self, callback) -> None:  # type: ignore[type-arg]
        """Poll every 120 s; fire callback for any activity ID not seen before."""

        def _poll() -> None:
            try:
                existing = self._svc().get_activities(0, 20)
                known: set[str] = {str(a["activityId"]) for a in existing if a.get("activityId")}
            except Exception:
                known = set()

            while True:
                time.sleep(self._POLL_INTERVAL)
                try:
                    activities = self._svc().get_activities(0, 20)
                    for act in activities:
                        aid = str(act.get("activityId", ""))
                        if aid and aid not in known:
                            known.add(aid)
                            callback(self._format_activity(act))
                except Exception:
                    pass

        t = threading.Thread(target=_poll, daemon=True, name="garmin-on_new_activity")
        t.start()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _svc(self):
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self):
        from garminconnect import Garmin

        if self._token_dir.exists():
            try:
                # garth handles token refresh automatically
                client = Garmin()
                client.garth.load(str(self._token_dir))
                return client
            except Exception:
                pass  # corrupted or incompatible tokens — fall through to fresh login

        if not self._credentials_file.exists():
            self._credentials_file = self._prompt_and_save_credentials()

        creds = json.loads(self._credentials_file.read_text())
        client = Garmin(email=creds["email"], password=creds["password"])
        try:
            client.login()
        except Exception as exc:
            from garminconnect import (
                GarminConnectAuthenticationError,
                GarminConnectTooManyRequestsError,
            )

            if isinstance(exc, GarminConnectTooManyRequestsError):
                raise RuntimeError(
                    "Garmin bloqueou por excesso de tentativas (IP rate limit). "
                    "Aguarde alguns minutos e tente de novo."
                ) from exc
            if isinstance(exc, GarminConnectAuthenticationError):
                self._credentials_file.unlink(missing_ok=True)
                raise RuntimeError(
                    "Email ou senha incorretos. "
                    "As credenciais foram removidas — tente de novo para reinserir."
                ) from exc
            raise

        self._token_dir.mkdir(parents=True, exist_ok=True)
        client.garth.dump(str(self._token_dir))
        return client

    def _prompt_and_save_credentials(self) -> Path:
        """Interactively ask for Garmin credentials and save them to disk."""
        print(f"\n[Garmin] Credenciais não encontradas: {self._credentials_file}")
        print(
            "[Garmin] Informe suas credenciais Garmin Connect (salvas localmente, usadas uma vez):"
        )
        email = input("  Email: ").strip()
        password = _read_password("  Senha: ")

        self._credentials_file.parent.mkdir(parents=True, exist_ok=True)
        self._credentials_file.write_text(
            json.dumps({"email": email, "password": password}, indent=2)
        )
        print(f"[Garmin] Credenciais salvas em {self._credentials_file}")
        return self._credentials_file

    def _stats_today(self) -> dict:
        return self._svc().get_stats(date.today().isoformat()) or {}

    def _format_sleep(self, dto: dict) -> dict:
        def _sec_to_h(sec: int | None) -> float | None:
            return round(sec / 3600, 2) if sec else None

        sleep_scores = dto.get("sleepScores") or {}
        overall = sleep_scores.get("overall") or {} if isinstance(sleep_scores, dict) else {}
        score = overall.get("value") if isinstance(overall, dict) else None

        return {
            "total_sleep_h": _sec_to_h(dto.get("sleepTimeSeconds")),
            "deep_h": _sec_to_h(dto.get("deepSleepSeconds")),
            "light_h": _sec_to_h(dto.get("lightSleepSeconds")),
            "rem_h": _sec_to_h(dto.get("remSleepSeconds")),
            "awake_h": _sec_to_h(dto.get("awakeSleepSeconds")),
            "score": score,
            "start_gmt": dto.get("sleepStartTimestampGMT"),
            "end_gmt": dto.get("sleepEndTimestampGMT"),
        }

    def _format_activity(self, raw: dict) -> dict:
        activity_type = raw.get("activityType") or {}
        return {
            "id": raw.get("activityId"),
            "name": raw.get("activityName"),
            "type": activity_type.get("typeKey") if isinstance(activity_type, dict) else None,
            "start": raw.get("startTimeLocal"),
            "duration_min": round((raw.get("duration") or 0) / 60, 1),
            "distance_km": round((raw.get("distance") or 0) / 1000, 2)
            if raw.get("distance")
            else None,
            "calories": raw.get("calories"),
            "avg_hr": raw.get("averageHR"),
            "max_hr": raw.get("maxHR"),
            "avg_pace_min_km": raw.get("averageSpeed"),  # raw unit — AI can convert
        }
