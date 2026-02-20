---
name: git-advanced-workflows
description: Advanced Git workflows for safe deployment and version control of the TitanBot project.
---

# Git Advanced Workflows for TitanBot

## 1. Branching Strategy (Git Flow Lite)
- **`main`**: Production-ready code. ALWAYS stable. Deployed to VPS.
- **`dev`**: Integration branch. All new features go here first.
- **`feature/xxx`**: Temporary branches for specific tasks (e.g., `feature/add-rsi`, `fix/websocket-bug`).

## 2. Safe Deployment Workflow
1.  **Develop:** Work in `feature/xxx`.
2.  **Test:** Run local tests (`pytest`).
3.  **Merge:** Merge to `dev`. Run integration tests.
4.  **Release:** Merge `dev` -> `main`.
5.  **Tag:** Create a version tag: `git tag -a v1.2 -m "Fixed WS bug"`.
6.  **Deploy:** Pull `main` on VPS.

## 3. Handling Sensitive Data
- **`.gitignore`**: Ensure `.env`, `__pycache__`, `*.log`, `*.db` are ignored.
- **Never commit secrets:** Use environment variables.

## 4. Emergency Hotfix
- If `main` is broken on VPS:
    1.  Checkout `main`.
    2.  Create `hotfix/xxx`.
    3.  Fix bug.
    4.  Merge to `main` AND `dev`.
    5.  Deploy immediately.

## 5. Useful Aliases
- `git lg`: `git log --graph --oneline --decorate --all` (Better history view).
- `git st`: `git status`.

## 6. VPS Sync
- Always use `git pull --rebase` on VPS to avoid messy merge commits if you made local changes on the server (though you shouldn't!).
