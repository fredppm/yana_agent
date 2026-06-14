"""
pulse — YANA autonomous observation engine.

Run as a standalone process:
    python -m pulse                      # uses defaults
    python -m pulse --port 7891          # custom API port

The Pulse process:
  - Loads pulse-tasks.yaml from the sanctum
  - Schedules tasks with APScheduler
  - Executes tasks against YANA connectors
  - Delivers results to YANA sessions
  - Exposes a localhost HTTP API for YANA to manage tasks
"""
