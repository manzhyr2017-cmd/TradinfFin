---
name: linux-server-security
description: Security hardening guide for Linux VPS hosting trading bots.
---

# Linux Server Security (VPS Hardening)

## 1. User Management
- **Disable Root Login:** Edit `/etc/ssh/sshd_config` -> `PermitRootLogin no`.
- **Create Sudo User:** Create a dedicated user for administration (`adduser admin`, `usermod -aG sudo admin`).
- **SSH Keys Only:** Disable password authentication (`PasswordAuthentication no`). Use SSH keys.

## 2. Firewall (UFW)
- **Deny All Incoming:** `ufw default deny incoming`.
- **Allow Specific:**
    - `ufw allow ssh` (or custom port).
    - `ufw allow 80/tcp` (if hosting web UI).
    - `ufw allow 443/tcp` (SSL).
- **Enable:** `ufw enable`.

## 3. Intrusion Prevention (Fail2Ban)
- **Install:** `apt install fail2ban`.
- **Configure:** Set up jails for SSH (ban IP after 3-5 failed login attempts).
- **Monitor:** Check banned IPs `fail2ban-client status sshd`.

## 4. System Updates
- **Auto-Updates:** Enable `unattended-upgrades` package for security patches.
- **Regular Maintenance:** Run `apt update && apt upgrade` manually periodically.

## 5. Process Isolation
- **Docker:** Running apps in containers adds a layer of isolation.
- **AppArmor/SELinux:** Use mandatory access control if high security is required.

## 6. Audit & Logging
- **Logwatch:** Install `logwatch` to get daily email summaries of server activity.
- **Check Auth Logs:** Regularly inspect `/var/log/auth.log`.
