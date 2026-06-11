# Connector API Reference

Companion to `SPEC.md`. Contains the load-bearing interface definitions for CAP-1, CAP-4, and CAP-5.

---

## Data Structures

### Schema Field

Used in both `params` and `returns`:

```python
{
  "type":    "boolean" | "number" | "string" | "array" | "object" | "list",
  "unit":    str,   # optional — physical quantities only: "bpm", "steps/day", "km", "kcal"
  "format":  str,   # optional — composite types: "rgb", "rgba", "iso8601", "wled_effect"
  "required": bool  # optional — only meaningful in params, defaults True
}
```

### ConnectorResult

Returned by every `call()` invocation:

```python
{
  "ok":    bool,
  "data":  Any,                  # present when ok=True
  "error": str | None            # "timeout" | "auth" | "unavailable" | "validation_error"
}
```

---

## Connector Type Contract

A connector type is a Python class. The framework derives the contract from its decorators.

### `@query`

Declares a read-only operation. Does not change state in the external system.

```python
@query(
    description: str,           # mandatory — natural language for AI
    params: dict = {},          # optional — {param_name: SchemaField}
    returns: dict               # mandatory — SchemaField
)
def method_name(self, **params) -> Any:
    ...
```

### `@command`

Declares a state-changing operation.

```python
@command(
    description: str,           # mandatory
    params: dict = {},          # optional
    returns: dict = {"type": "boolean"}  # defaults to ack boolean
)
def method_name(self, **params) -> Any:
    ...
```

### `@event`

Declares a push notification capability. The method receives a `callback` and is responsible for detecting the event by any means (internal polling, webhook, stream).

```python
@event(
    description: str,           # mandatory
    schema: dict                # mandatory — shape of the event payload
)
def on_event_name(self, callback: Callable) -> None:
    # framework calls this once at registration
    # implementation calls callback(payload) when event fires
    ...
```

---

## ConnectorInstance (Manifest Entry)

```yaml
- type: GarminActivity          # ConnectorType class name
  id: garmin_fred               # unique, stable identifier
  name: "Garmin do Fred"        # human/AI label
  description: "Dados de saúde e atividade física do Fred"  # one-line for manifest
  owner: fred                   # optional — omit for generic connectors
```

---

## Call Interface

```python
call(instance_id: str, operation: str, params: dict = {}) -> ConnectorResult
```

- `instance_id` — matches `id` in the manifest
- `operation` — matches a decorated method name on the ConnectorType
- `params` — validated against the operation's `params` schema before dispatch

The framework rejects the call with `{ ok: false, error: "validation_error" }` if params fail schema validation, before the implementation method is invoked.

---

## Manifest Levels

**Level 1 — Lightweight (always in AI context):**

```yaml
connectors:
  - id: garmin_fred
    name: "Garmin do Fred"
    description: "Dados de saúde e atividade física do Fred"
  - id: calendar_fred
    name: "Agenda do Fred"
    description: "Eventos e compromissos do calendário pessoal do Fred"
  - id: rgb_sala
    name: "Luz da Sala"
    description: "Luz RGB da sala de estar"
```

**Level 2 — Full contract (loaded on demand per instance):**

Complete set of decorated methods with descriptions, param schemas, and return schemas — derived at runtime from the Python class.

---

## Example Connector

```python
class GarminActivityConnector(Connector):

    @query(
        description="Passos dados hoje",
        returns={"type": "number", "unit": "steps/day"}
    )
    def steps_today(self) -> int:
        return self._api.get_steps_today()

    @query(
        description="Nível de stress atual (0–100)",
        returns={"type": "number", "unit": "stress_score"}
    )
    def stress_level(self) -> int:
        return self._api.get_stress()

    @query(
        description="Última atividade de corrida registrada",
        returns={"type": "object"}
    )
    def last_run(self) -> dict:
        return self._api.get_last_activity(type="running")

    @command(
        description="Sincroniza dados do dispositivo manualmente",
        returns={"type": "boolean"}
    )
    def sync(self) -> bool:
        return self._api.force_sync()

    @event(
        description="Nova atividade física registrada",
        schema={"type": "object", "fields": ["activity_type", "duration_min", "calories"]}
    )
    def on_new_activity(self, callback):
        # implementation decides HOW to detect — internal polling, webhook, etc.
        ...
```
