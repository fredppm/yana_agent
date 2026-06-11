# Pulse

## Configuration

Read `pulse-config.yaml` in the sanctum root before executing any task. It controls per-task frequency and enabled state. If the file is missing, use the defaults below.

```yaml
# pulse-config.yaml defaults (copy to sanctum and edit to customize)
quiet_hours: "23:00-07:00"

scheduled:
  memory_curation:  { frequency: "2x/day",  enabled: true  }
  price_watch:      { frequency: "3x/day",  enabled: true  }
  email_digest:     { frequency: "1x/day",  enabled: true  }
  agenda_review:    { frequency: "2x/day",  enabled: true  }
  self_improvement: { frequency: "1x/week", enabled: true  }
```

> Future versions may support per-item granularity (e.g. specific products on different schedules). Design with that in mind — keep the config structure extensible.

## On Quiet Rebirth (Scheduled)

When invoked via `--headless` without a specific task, read `pulse-config.yaml`, check quiet hours, then work through enabled scheduled tasks in priority order. Load `references/memory-guidance.md` for memory discipline before writing anything.

### Memory Curation

Your goal: when Fred activates you next session and reads MEMORY.md, you should have everything needed to be immediately effective — nothing stale, nothing missing, nothing wasting context.

Review recent session logs in `sessions/`. Extract what matters. Prune what's resolved or obvious. Surface patterns across sessions. Keep MEMORY.md under 200 lines.

Check BOND.md — has anything about Fred's patterns, facets, or preferences changed?

### Price Watch

Check prices of products in the Tracked Items section of MEMORY.md. For each item:
- If price has dropped to or below target, append a flag to `pulse-alerts.md`
- If tracked > 30 days without a purchase, flag it — he may have lost interest
- Update the "current price" field

### Email Digest

When email access is configured (Google work + personal), scan for high-priority items:
- Work: newsletters, VTEX-related, anything requiring action
- Personal: important threads, shipping notifications, home/family logistics

Summarize into `pulse-digest-YYYY-MM-DD.md`. Flag the 3-5 items actually worth Fred's attention.

### Agenda Review

When calendar access is configured (two Google accounts), scan the next 48 hours:
- Conflicts, tight transitions, gaps needing preparation
- Anything connected to pending tasks in MEMORY.md

Append findings to `pulse-digest-YYYY-MM-DD.md`.

### Self-Improvement

Reflect on recent sessions. What worked? What fell flat? Capability gaps? Note findings in session log for discussion next session.

---

## On Triggered Rebirth (Event-Driven)

When invoked via `--headless:trigger --source <source> --event <event> --payload <json>`, check `pulse-config.yaml` first — if the source is not enabled, exit quietly. Otherwise execute the matching handler below.

All trigger sources are optional and independent. PULSE works fully without any of them active.

### Trigger Handlers

| Source | Event | Action |
|--------|-------|--------|
| `home_assistant` | `stock_low` | Load smart-shopping capability, research the item, append suggestion to `pulse-alerts.md` |
| `home_assistant` | `sensor_alert` | Log the alert, assess if action needed, append to `pulse-alerts.md` |
| `garmin` | `stress_high` | Note pattern in BOND.md, queue a gentle life-coach check-in for next session |
| `garmin` | `sleep_poor` | Note in BOND.md, adjust tone expectation for today's session |
| `calendar` | `free_slot` | Log the window in `pulse-digest-YYYY-MM-DD.md` with a suggestion |

> To add a new trigger source: add a row to this table, add it to `pulse-config.yaml`, and document the expected payload. To remove a source: set `enabled: false` in `pulse-config.yaml` — no other changes needed.

---

## Scheduled Task Routing

| Task | Invocation | Action |
|------|-----------|--------|
| Memory curation | `--headless:memory` | Curation only |
| Price watch | `--headless:price-watch` | Price check only |
| Email digest | `--headless:email-digest` | Email digest only |
| Agenda review | `--headless:agenda-review` | Agenda review only |
| Full pulse | `--headless` | All enabled tasks in priority order |

## Quiet Hours
{Confirmed during First Breath. Default: 23:00–07:00 local time. Triggered tasks respect quiet hours unless marked urgent.}

## State
_Maintained by the agent. Last check timestamps, pending alerts._

| Check | Last Run | Next Scheduled |
|-------|----------|----------------|
| Memory curation | — | — |
| Price watch | — | — |
| Email digest | — | — |
| Agenda review | — | — |
