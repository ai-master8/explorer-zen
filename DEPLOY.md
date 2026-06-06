# Deploying explorer-zen on a Linux VPS

This guide shows how to run `explorer-zen` on a remote Ubuntu VPS and connect to its live terminal dashboard over SSH. The setup uses `tmux` (persistent session) plus a `systemd` unit (auto-start on boot and after crashes). No third-party Python packages are required.

The script is already cross-platform — it uses `select`+`tty.setcbreak`+`termios` for Q-key detection on Unix, and `\x1b[2J\x1b[H` for screen clear. No code changes are required to run on Linux.

## Requirements

- Ubuntu 22.04 LTS or 24.04 LTS (Python 3.10 / 3.12 preinstalled)
- OpenSSH server reachable from your local machine
- Outbound HTTPS to `openrouter.ai` and `ru.wikipedia.org`
- A local SSH key (Ed25519 recommended)

## 1. One-time VPS preparation (run as `root`)

```bash
apt update && apt install -y tmux python3 git
locale-gen en_US.UTF-8
update-locale LANG=en_US.UTF-8

# Create a non-root user
adduser explorer --disabled-password --gecos ""
```

## 2. SSH key (run on your **local** machine)

If you don't have a key yet (Windows PowerShell):

```powershell
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\id_ed25519
```

Copy the public key to the VPS:

```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@<VPS_IP> "tee -a /home/explorer/.ssh/authorized_keys && chmod 600 /home/explorer/.ssh/authorized_keys && chown -R explorer:explorer /home/explorer/.ssh"
```

Test passwordless login:

```bash
ssh explorer@<VPS_IP> "whoami; echo OK"
```

Optional: add an alias to `~/.ssh/config` so you can run `ssh explorer` instead of typing the IP:

```
Host explorer
    HostName <VPS_IP>
    User explorer
```

## 3. Clone the repo (as `explorer`)

```bash
sudo -iu explorer
cd ~
git clone https://github.com/ai-master8/explorer-zen.git
cd explorer-zen
chmod +x explorer_zen.py
```

## 4. Store the API key in an EnvironmentFile (as `root`)

This file is read by the systemd unit. It is owned by `root`, mode 0600, and lives in `/etc/explorer-zen/` — never in the repo.

```bash
install -d -m 700 /etc/explorer-zen
install -m 600 /dev/null /etc/explorer-zen/env
# Edit the file and put the key in OPENROUTER_API_KEY=...
$EDITOR /etc/explorer-zen/env
chown -R root:root /etc/explorer-zen
```

The file should look like:

```
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxx
```

## 5. Smoke test (as `explorer`)

Run a single session and exit. This validates the key, the network, the UTF-8 locale, and that the script writes `memory.json` and a `reports/*.md` file.

```bash
cd ~/explorer-zen
OPENROUTER_API_KEY=$(sudo cat /etc/explorer-zen/env | cut -d= -f2) \
  python3 -u explorer_zen.py --once
```

You should see the dashboard cycle through `ПРОБУЖДЕНИЕ → ПОИСК В ВИКИПЕДИИ → ЗАПРОС К ИИ → ПАРСИНГ ОТВЕТА → КОМПИЛЯЦИЯ ОТЧЁТА → СЕССИЯ УСПЕШНО СИНХРОНИЗИРОВАНА → РАЗОВЫЙ ЗАПУСК ЗАВЕРШЁН`, then exit cleanly.

If anything goes wrong, the most common cause is a network/firewall block. Test from the VPS directly:

```bash
curl -sI https://ru.wikipedia.org | head -1
curl -sI https://openrouter.ai | head -1
```

## 6. systemd unit (as `root`)

The unit starts a detached `tmux` session on boot, runs the agent in the foreground of that session, and pipes the output (with `tee`) to `explorer.log` for after-the-fact debugging. `Restart=on-failure` brings the agent back if it crashes.

```bash
cat > /etc/systemd/system/explorer-zen.service <<'EOF'
[Unit]
Description=explorer-zen AI researcher (tmux session)
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
User=explorer
WorkingDirectory=/home/explorer/explorer-zen
EnvironmentFile=/etc/explorer-zen/env
ExecStart=/usr/bin/tmux new-session -d -s explorer -c /home/explorer/explorer-zen 'python3 -u explorer_zen.py 2>&1 | tee -a /home/explorer/explorer-zen/explorer.log'
ExecStop=/usr/bin/tmux send-keys -t explorer q
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now explorer-zen.service
systemctl status explorer-zen.service
```

`ExecStop` sends `q` to the tmux session — the script's Q-key handler picks it up, prints a clean `ОСТАНОВКА ПО ЗАПРОСУ` dashboard frame, and exits. `systemctl stop` is then clean.

## 7. Connect to the live TUI dashboard

From your local machine:

```bash
ssh explorer@<VPS_IP> -t "tmux attach -t explorer"
```

Or in two steps:

```bash
ssh explorer@<VPS_IP>
tmux attach -t explorer
```

Inside tmux:
- The dashboard refreshes once per second.
- `Q` (or `й` in Russian layout) stops the agent cleanly.
- `Ctrl+B`, then `D` — detach from the session. The agent keeps running.
- Re-attach later with `tmux attach -t explorer`.

If the terminal is too narrow for the dashboard, the script auto-detects `os.get_terminal_size()` and truncates. Minimum width is ~60 columns.

## 8. Operations cheatsheet

| Task | Command |
|---|---|
| Attach to the dashboard | `tmux attach -t explorer` |
| Detach | `Ctrl+B`, then `D` |
| Stop the agent | press `Q` inside the session, **or** `sudo systemctl stop explorer-zen` |
| Start the agent | `sudo systemctl start explorer-zen` |
| Tail the log file | `tail -f /home/explorer/explorer-zen/explorer.log` |
| Check the last report | `ls -lt /home/explorer/explorer-zen/reports/ \| head -1` |
| Inspect `memory.json` | `cat /home/explorer/explorer-zen/memory.json \| python3 -m json.tool` |
| Update to the latest code | `sudo -iu explorer -c "cd ~/explorer-zen && git pull && sudo systemctl restart explorer-zen"` |

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `╔═║` renders as `?` or boxes | Server locale is not UTF-8 | `localectl set-locale LANG=en_US.UTF-8` and re-login |
| `python3: command not found` | Minimal Ubuntu image | `apt install python3` |
| `tmux: command not found` | Forgot to install tmux | `apt install tmux` |
| `ModuleNotFoundError: No module named 'msvcrt'` | This should not happen — `msvcrt` is only imported under `os.name == 'nt'` | Check you're not running the Windows version; the script auto-branches |
| Service keeps restarting every 10s | Hard crash in the script (uncaught exception) | `tail -50 /home/explorer/explorer-zen/explorer.log` to see the traceback; usually a transient OpenRouter overload or a Wikipedia change |
| Q-key does nothing | Terminal is not a real TTY (e.g. running inside a non-tty pipe) | Use `ssh -t` to force a TTY, or run inside `tmux`/`screen` |
| All sessions return `429` | OpenRouter free-tier overload | Increase `MAX_RETRIES` / `BASE_DELAY` in `explorer_zen.py`, or wait |
| Wikipedia returns `пустой поиск` repeatedly | The LLM hallucinates non-existent article titles; the `next_query` rotates after 3 empty searches in a row | No action — rotation picks a topic from `long_term_knowledge` or `CYCLE_FALLBACK_TOPICS` |
| Stale dashboard after a long SSH disconnect | tmux session is intact; just re-attach | `tmux attach -t explorer` |

## 10. Surviving reboots

The systemd unit already starts the agent automatically on boot. To additionally survive a forced tmux crash (rare), the agent restarts within 10 seconds thanks to `Restart=on-failure`.

For full session persistence across reboots (e.g. keeping the exact tmux layout and any additional windows), install `tmux-resurrect` and `tmux-continuum`:

```bash
sudo -iu explorer
git clone https://github.com/tmux-plugins/tmux-resurrect ~/.tmux/plugins/tmux-resurrect
git clone https://github.com/tmux-plugins/tmux-continuum ~/.tmux/plugins/tmux-continuum

cat > ~/.tmux.conf <<'EOF'
run-shell ~/.tmux/plugins/tmux-resurrect/resurrect.tmux
run-shell ~/.tmux/plugins/tmux-continuum/continuum.tmux
set -g @continuum-save-interval '15'
set -g @continuum-restore 'on'
EOF
```

`explorer-zen` only uses one window (the `explorer` session), so `tmux-resurrect` mostly helps if you add more sessions later.

## 11. Security notes

- The OpenRouter API key is in `/etc/explorer-zen/env`, mode 0600, owned by `root`. It is not in the repo, not in `~/.bashrc`, and not in any world-readable file.
- The agent writes to `~/explorer-zen/memory.json` and `~/explorer-zen/reports/`. Both are git-ignored.
- The script does not bind to any network port — it only makes outbound HTTPS calls.
- If you stop using the VPS, rotate the API key in your OpenRouter dashboard.
