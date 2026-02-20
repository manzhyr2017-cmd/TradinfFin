---
name: systematic-debugging
description: A structured approach to debugging complex systems like trading bots on remote servers.
---

# Systematic Debugging for TitanBot

## 1. Reproduce the Issue
- NEVER start fixing until you can reproduce the bug.
- If it's a rare race condition, add extensive logging around the suspected area.

## 2. Check the Logs First
- **VPS Location:** `bot.log` or screen output.
- **Keywords:** Search for `ERROR`, `WARNING`, `Traceback`, `Exception`.
- **Context:** Look at the 10 lines *before* the error to understand the state.

## 3. Isolate the Component
- Determine if the issue is in:
    - **Data Layer:** `DataEngine` (API, WebSocket)
    - **Logic Layer:** `CompositeScore`, `Strategy`
    - **Execution Layer:** `OrderExecutor`
    - **Infrastructure:** Network, VPS memory, Disk space

## 4. The "Rubber Duck" Method
- Explain the code logic line-by-line to the AI or a rubber duck. Often the logic error becomes obvious during explanation.

## 5. Remote Debugging Tools
- Use `pdb` (Python Debugger) if you can run the bot interactively.
- Add "breadcrumb" logs: `print(f"DEBUG: Entering function X with args {args}")`.

## 6. Validate Assumptions
- Don't assume "the API always returns data". Check for `None`, empty lists `[]`, or malformed JSON.
- Don't assume "the network is stable". Handle timeouts and disconnects gracefully.

## Incident Report Template
When a bug is fixed, document it:
- **Symptom:** What happened?
- **Root Cause:** Why did it happen?
- **Fix:** What code was changed?
- **Prevention:** How to ensure it never happens again (Test? Assert?).
