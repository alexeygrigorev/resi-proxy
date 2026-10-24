# resi-proxy

Residential HTTP proxy service for Hetzner, with per-location systemd user
units and one reconnecting SSH tunnel on the Grok Bot box. The local endpoints are
unauthenticated and bind **127.0.0.1 only**. Keep them private.

## Install on Hetzner

Requires Linux, Python 3, Node.js 18+, npm, curl, and systemd user services.

```bash
git clone git@github.com:alexeygrigorev/resi-proxy.git
cd resi-proxy
./install.sh
export PATH="$HOME/.local/bin:$PATH"
loginctl enable-linger "$USER"   # once, if linger is not already enabled
```

Installation copies runtime files to `~/.local/share/resi-proxy`, links
`~/.local/bin/proxy`, and installs the three templates from `systemd/` with the
current Node/Python executable paths. The checkout/worktree can then be removed.
Run `./install.sh` again to upgrade; restart running instance services to load
forwarder changes. The CLI defaults to the account's real home directory, even
when an agent has an isolated HOME.

Credentials are read from the process environment or `~/.config/youtube/.env`
(environment wins). Use `.env.example` as a template and mode 600. To use another
file, set `RESI_PROXY_ENV_FILE`; for watchdogs also set that variable in a systemd
override for `resi-proxy-watchdog@.service`. Never put credentials in a unit,
command argument, report, or committed file. Env files are parsed as assignments,
not executed as shell scripts. `DATAIMPULSE_ENDPOINT` accepts a host:port or an
HTTP(S) origin without embedded credentials; the default is `gw.dataimpulse.com:823`.

## Location CLI

```bash
proxy up --country cn --sticky --port 18090
proxy up --country jp --sticky --port 18082
proxy up --country cn --state guangdong --sticky
proxy up --country cn --city shanghai --sticky --port 18101
proxy list
proxy list --ports                    # active service ports, one per line
proxy list --json                     # includes targeting cost and active state
proxy status                         # all configured instances, probes ipinfo.io
proxy status jp --json
proxy rotate jp                      # new sessid, then bounded country check
proxy down jp                        # stop unit/timer; retain private config
proxy down                           # all instances
```

Names are `cn`, `jp`, `cn-state-guangdong`, or `cn-city-shanghai`. Each location
owns one port and its own `resi-proxy@NAME.service` and
`resi-proxy-watchdog@NAME.timer`. Omitted ports allocate from 18100 upwards;
explicit ports must be 1024–65535. An occupied port is rejected before activation.
Bring an instance down before changing its config. Re-running an identical `up`
preserves the sticky session. `--prepare` writes private config without starting
anything, useful before a migration.

Country-only targeting is standard traffic cost; **state/city targeting costs
2x traffic**, is opt-in, and is displayed in `list`. State and city are mutually
exclusive location slugs. The upstream login is formed as
`LOGIN__cr.cn;city.shanghai;sessid.X;sessttl.N` (or `state.guangdong`); parameters
after `__` are semicolon-separated. Credentials and parameters are URL-encoded.
Sticky TTL is `--ttl 1..120`, default 120 minutes. Without `--sticky`, gateway 823
rotates per connection; `rotate` refreshes credentials and checks its country,
while each connection already requests a fresh upstream. A successful status
check describes that probe's exit; it cannot guarantee the next rotating exit.
Do not rotate a sticky session during login/checkout. Automatic country recovery
can change the IP when a session stops matching, so recheck before checkout.

`proxy status` prints port, location, exit IP, ipinfo country/region/city, and
`OK`, `MISMATCH`, `ERROR`, or `DOWN`; non-OK exits return status 1. The watchdog
checks every three minutes and performs up to eight checks with at most seven
rotations. **CN requires `country == CN`; HK is a mismatch.** `NO_RAY` means no IP
is available for that geo; status and watchdog logs surface it. Some upstream
CONNECT failures omit the reason; HTTP 400 is reported as possible NO_RAY.
A failed `up` leaves the service and watchdog enabled for recovery; use `down`
to stop it. Probes have a 20-second timeout. Health checks consume some traffic.

```bash
systemctl --user status resi-proxy@cn.service resi-proxy-watchdog@cn.timer
journalctl --user -u resi-proxy-watchdog@cn.service -n 20 -o cat
proxy watchdog cn                    # manually run the bounded country check
```

Config is `~/.config/resi-proxy/NAME/config.json`; runtime upstream URLs are
atomically written as `upstream.url`, mode 600, in private directories. The
forwarder rereads the file per connection, so rotation requires no restart.
Logs use fixed sanitized errors and never library exception text or URLs.
`RESI_PROXY_HOME` and `RESI_PROXY_CONFIG` are available for isolated CLI tests;
installed units use the standard account paths.

## One box tunnel for all active ports

The box cannot reach DataImpulse directly; credentials stay on Hetzner. Copy
`box/resi-tunnel.sh` to `/home/box/bin/resi-tunnel.sh`, mode 755. SSH alias
`hetzner` must work noninteractively. The script uses the explicit remote command
`"$HOME/.local/bin/proxy" list --ports`, so noninteractive SSH needs no PATH setup.

Replace the old CN-only startup line at the **top** of box `~/.bashrc` with:

```bash
/home/box/bin/resi-tunnel.sh ensure >/dev/null 2>&1
```

During box migration, first stop `/home/box/bin/cn-tunnel-18090.sh stop` and any
old JP-only SSH tunnel, then immediately run the new `ensure`. Keep the old files
for deletion approval. Competing tunnels cannot bind the same local ports.

```bash
/home/box/bin/resi-tunnel.sh ensure    # nonblocking; flock guards one supervisor
/home/box/bin/resi-tunnel.sh status
/home/box/bin/resi-tunnel.sh stop
/home/box/bin/resi-tunnel.sh dry-run   # discover ports, show SSH command only
curl --max-time 30 -x http://127.0.0.1:18090 https://ipinfo.io/json  # must be CN
curl --max-time 30 -x http://127.0.0.1:18082 https://ipinfo.io/json  # must be JP
```

One SSH `-N` process has one `-L` per active port. The supervisor checks discovery
and SSH liveness every 30 seconds, reconnects when ports change or SSH exits,
and falls back to the last valid port list on discovery failure. Successful empty
discovery closes all forwards. `ExitOnForwardFailure` avoids partial startup.
Private state/log/cache live in `~/.local/state/resi-tunnel`. `status` reports the
supervisor, requested ports, listeners, and recent log; verify exits with curl.
For selected ports, set `RESI_TUNNEL_PORTS=18090,18082` consistently in the startup
environment. `RESI_TUNNEL_HOST`, `RESI_TUNNEL_STATE`, and
`RESI_TUNNEL_INTERVAL` override host, state directory, and refresh interval.

Local dry-run without a box or network:

```bash
RESI_TUNNEL_PORTS=18082,18090 box/resi-tunnel.sh dry-run
python3 -m unittest discover -s tests -v
```

The tunnel integration test uses a fake SSH endpoint to verify singleton startup,
port refresh, cached fallback, and stop cleanup. Actual box curl tests require the
orchestrator to install the script on the box and run the commands above.

## Existing service migration and rollback

Preserve CN port **18090** and JP port **18082**. Never use China 18090 for Japan.
Port 18080 belongs to an unrelated Docker app and must remain untouched.

1. Prepare JP with `proxy up --country jp --sticky --port 18082 --prepare`.
   Confirm the old listener is `/tmp/proxyfwd-jp/start.mjs`, stop that PID, then
   repeat `up` without `--prepare` and verify JP.
2. Prepare CN with the analogous `--country cn --sticky --port 18090 --prepare`.
   Privately copy the old `~/.config/proxyfwd-cn18090/upstream.url` over the new
   `~/.config/resi-proxy/cn/upstream.url` (mode 600) to preserve the current session.
   Stop/disable `proxyfwd-cn18090-watchdog.timer`, stop its oneshot service, and
   stop/disable `proxyfwd-cn18090.service`. Immediately run the new CN `up` and
   verify mainland CN. If activation/check fails, `proxy down cn` and
   `systemctl --user enable --now proxyfwd-cn18090.service proxyfwd-cn18090-watchdog.timer`.
3. Stop the confirmed old `/tmp/proxyfwd/start.mjs` listener on 18081.
   **Do not delete** old directories, configs, scripts, or unit files; list them
   for explicit deletion approval. Disabling replaced units is sufficient.

## Secret-history check

Run gitleaks/trufflehog when available. Otherwise scan all reachable history
objects for the exact credential values read privately from the env file, report
only pass/fail and object counts, and never echo matching lines. Scan again after
the final commit and before pushing. Runtime credentials, `.env`, configuration,
node_modules, and agent `.local/` artifacts are excluded by `.gitignore`.
