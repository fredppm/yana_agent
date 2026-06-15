# Pulse Task Schema

Every Pulse task has exactly three top-level fields. The runner rejects tasks missing any field.

## Fields

### `observe`

What the task monitors and which connector provides the data.
YANA resolves the natural language intent into `operation` + `params` when creating the task config.

| Sub-field | Type | Description |
|---|---|---|
| `source` | string | Connector instance ID (e.g. `gmail_fred_personal`) |
| `operation` | string | Connector operation name (e.g. `search`, `unread_important`) |
| `params` | object | Operation parameters as key/value pairs. Optional — defaults to `{}`. |

### `schedule`

When the task runs. MVP supports `fixed` mode only.

| Sub-field | Type | Description |
|---|---|---|
| `mode` | `fixed` | Schedule mode. Only `fixed` in MVP. |
| `time` | `HH:MM` | Time of day to run (local timezone) |
| `days` | string | `daily`, `weekdays`, `weekends`, or ISO weekday list (e.g. `mon,wed,fri`) |

### `deliver`

What to do with the result.

| Sub-field | Type | Description |
|---|---|---|
| `action` | `summarize` \| `notify` \| `store` | How to process the raw result |
| `prompt` | string | Instruction to the LLM for `summarize` action |

## Example

```yaml
tasks:
  - name: newsletter-summary
    observe:
      source: gmail_fred_personal
      operation: search
      params:
        query: "category:promotions is:unread"
    schedule:
      mode: fixed
      time: "10:00"
      days: daily
    deliver:
      action: summarize
      prompt: "Summarize these newsletter emails in Portuguese. Extract the key points from each sender. Be concise."
```

## Runner Behavior

- Tasks are loaded at startup from the task config file.
- Each task runs in its own isolated execution context.
- Failures trigger retry with exponential backoff: 1 min → 3 min → 9 min (3 attempts total).
- After 3 failures, an error notification is written to the Pulse session.
- Task execution is sequential (no parallel execution in MVP).
