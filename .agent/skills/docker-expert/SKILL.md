---
name: docker-expert
description: Guidelines for containerizing applications using Docker and Docker Compose, tailored for Python trading bots.
---

# Docker Expert Guide for TitanBot

## 1. Dockerfile Best Practices
- **Base Image:** Use slim python images (e.g., `python:3.11-slim-bookworm`) to reduce size and attack surface.
- **Multi-Stage Builds:** Separate build dependencies (gcc, headers) from runtime (app code).
- **Non-Root User:** NEVER run the container as root. Create a `titan` user inside the image.
- **Layers:** Order instructions from least to most frequently changed (dependencies first, code last) to optimize caching.

## 2. Docker Compose Configuration
- **Services:** Define `bot`, `postgres`, `redis` as separate services.
- **Restart Policies:** Use `restart: unless-stopped` for resilience.
- **Networks:** Isolate backend services (DB) from public access. Only expose necessary ports.
- **Healthchecks:** Add `healthcheck` to ensure dependent services are ready before starting the bot.

## 3. Environment Variables
- **.env:** Mount `.env` file but ensure it's not committed to git.
- **Secrets:** For sensitive data in production (API keys), use Docker Secrets or environment injection.

## 4. Volume Management
- **Persistence:** Mount volumes for logs (`./logs:/app/logs`) and database data (`pgdata:/var/lib/postgresql/data`).
- **Time Sync:** Ensure container time is synced with host (`-v /etc/localtime:/etc/localtime:ro`). Critical for trading!

## 5. Maintenance Commands
- `docker-compose up -d --build` - Build and start in background.
- `docker-compose logs -f --tail=100 bot` - View live logs.
- `docker system prune -a` - Clean up unused images/containers.
