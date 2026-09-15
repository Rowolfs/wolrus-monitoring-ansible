# Ansible Centralized Monitoring

Production-ready, Docker-based centralized monitoring for small Linux fleets.
No Kubernetes, no Terraform — just Ansible + Docker Compose v2.

## Architecture

```
                       ┌─────────────────────────────────────────────┐
                       │            Central Grafana server            │
                       │            (inventory group: grafana)         │
                       │                                              │
                       │  Grafana  ◄──┐                               │
                       │  Prometheus ─┼──► Alertmanager ──► Telegram  │
                       │  Loki  ◄─────┘                               │
                       └──▲────────────────────────────▲──────────────┘
                          │ metrics (scrape)           │ logs (push)
                          │                            │
        ┌─────────────────┼────────────────────────────┼──────────────────┐
        │                 │                            │                  │
   ┌────┴─────┐      ┌────┴─────┐                ┌────┴─────┐      ┌────┴─────┐
   │  node01  │      │  node02  │      ...       │  node03  │      │   ...    │
   │ alloy    │      │ alloy    │                │ alloy    │      │          │
   │ node_exp │      │ node_exp │                │ node_exp │      │          │
   │ cadvisor │      │ cadvisor │                │ cadvisor │      │          │
   └──────────┘      └──────────┘                └──────────┘      └──────────┘
```

**Central Grafana server** (`grafana` group) runs in containers:
- **Grafana** — main UI, with Prometheus + Loki datasources auto-provisioned.
- **Prometheus** — scrapes metrics from all nodes.
- **Loki** — single-node, local-disk log storage (push from Alloy).
- **Alertmanager** — native Telegram integration, resolved notifications enabled.

**Remote nodes** (`nodes` group) run in containers:
- **Grafana Alloy** — discovers Docker containers, ships stdout/stderr logs to Loki.
- **node_exporter** — host metrics (CPU, memory, load, disk, filesystem, network).
- **cAdvisor** — Docker container metrics (CPU, memory, net I/O, filesystem).

### Data flow

| Data                    | Source          | Collector    | Destination        |
|-------------------------|-----------------|--------------|--------------------|
| Docker container logs  | nodes           | Grafana Alloy| Loki → Grafana     |
| Host metrics            | nodes           | node_exporter| Prometheus → Grafana|
| Docker container metrics| nodes           | cAdvisor     | Prometheus → Grafana|
| Alerts                  | Prometheus      | —            | Alertmanager → Telegram |

### Inventory groups

- **`grafana`** — the single central monitoring server.
- **`nodes`** — every monitored server running Docker.

Do **not** use group names like `monitoring`, `docker_hosts`, or `monitored_servers`.
The inventory is the single source of truth: Prometheus scrape targets and the
Loki push endpoint are generated automatically from these groups.

## Requirements

- Ansible >= 2.16 on the control machine.
- Python 3 on the control machine.
- Debian/Ubuntu target hosts (the `common` role adds the Docker APT repo).
- Docker + `docker compose` v2 are installed automatically by the `common` role.
- SSH access from the control machine to all hosts (as root, or a sudo-capable user).
- A private LAN/VPN between the grafana server and the nodes.

## Inventory configuration

Edit `inventories/production/hosts.yml`:

```yaml
all:
  children:
    grafana:
      hosts:
        grafana01:
          ansible_host: 10.0.0.10
    nodes:
      vars:
        ansible_user: root
      hosts:
        node01:
          ansible_host: 10.0.0.11
        node02:
          ansible_host: 10.0.0.12
        node03:
          ansible_host: 10.0.0.13
```

Never copy these IPs anywhere else — everything else is derived from the inventory.

## SSH configuration

Put your SSH settings in `~/.ssh/config` or set them per-host in the inventory.
Example inventory snippet with an explicit SSH key:

```yaml
all:
  children:
    grafana:
      hosts:
        grafana01:
          ansible_host: 10.0.0.10
          ansible_user: root
          ansible_ssh_private_key_file: ~/.ssh/id_ed25519
```

Verify connectivity:

```bash
ansible -i inventories/production/hosts.yml all -m ping
```

## Adding a new node

1. Add the host under `nodes:` in `inventories/production/hosts.yml`.
2. Re-run the deployment (see below).

That's it — Prometheus will automatically start scraping the new node's
`node_exporter` (port 9100) and `cAdvisor` (port 8080), and Alloy will start
shipping its container logs to Loki. No second list to maintain.

## Telegram configuration

1. Create a bot via [@BotFather](https://t.me/BotFather) → get the **bot token**.
2. Get your **chat id** (e.g. message [@userinfobot](https://t.me/userinfobot),
   or use a negative id for a group).
3. Store the values in the vault (see below) — never in plain group_vars.

Alertmanager uses its **native** `telegram_configs` receiver (Alertmanager
>= 0.27). Resolved notifications are enabled.

## Ansible Vault (secrets)

Secrets live in `inventories/production/group_vars/vault.yml`, which ships with
`CHANGE_ME` placeholders. Encrypt it before use:

```bash
# Edit the values first, then encrypt:
ansible-vault edit inventories/production/group_vars/vault.yml
ansible-vault encrypt inventories/production/group_vars/vault.yml

# Optional: store the vault password in a file for unattended runs
echo 'your-vault-secret' > .vault_pass
chmod 600 .vault_pass
# then uncomment `vault_password_file = .vault_pass` in ansible.cfg
```

Variables exposed to the roles:

| Variable                     | Source (vault.yml)             |
|------------------------------|--------------------------------|
| `grafana_admin_password`     | `vault_grafana_admin_password` |
| `telegram_bot_token`         | `vault_telegram_bot_token`     |
| `telegram_chat_id`           | `vault_telegram_chat_id`       |

## Running the deployment

Complete deployment (grafana server + all nodes):

```bash
ansible-playbook \
  -i inventories/production/hosts.yml \
  playbooks/deploy.yml
```

Add `--ask-vault-pass` (or use `.vault_pass`) once `vault.yml` is encrypted.

Grafana server only:

```bash
ansible-playbook \
  -i inventories/production/hosts.yml \
  playbooks/grafana.yml
```

Nodes only (exporters + Alloy):

```bash
ansible-playbook \
  -i inventories/production/hosts.yml \
  playbooks/nodes_exporters.yml
```

The playbooks are idempotent — running them repeatedly will not recreate
containers unless a configuration file actually changed.

## Firewall ports

Assume a private LAN/VPN. Required reachability:

**grafana server → nodes (outbound scrape):**
- `9100/tcp` (node_exporter)
- `8080/tcp` (cAdvisor)

**nodes → grafana server (outbound push):**
- `3100/tcp` (Loki, log push)

**grafana server (inbound, for users):**
- `443/tcp` (HTTPS, Caddy → Grafana) — public
- `80/tcp` (HTTP, Caddy ACME challenge + redirect to 443) — public

Grafana itself (`3000/tcp`) binds loopback-only behind Caddy; users reach it at
`https://<grafana_domain>` with automatic Let's Encrypt TLS.
Bound loopback-only (not exposed): Grafana `3000`, Prometheus `9090`,
Alertmanager `9093`.
node_exporter/cAdvisor/Alloy bind to the host over the private LAN — restrict
with a host firewall if the LAN is not fully trusted. Do **not** expose
Prometheus, Loki, Alertmanager, cAdvisor or node_exporter to the public Internet.

## Checking that everything works

On the grafana server:

```bash
# All containers up?
docker compose -f /opt/monitoring/docker-compose.yml ps

# Grafana health
curl -s http://127.0.0.1:3000/api/health

# Prometheus targets (all node_exporter + cadvisor should be UP)
curl -s http://127.0.0.1:9090/api/v1/targets | jq '.data.activeTargets[].health'

# Prometheus loaded alert rules
curl -s http://127.0.0.1:9090/api/v1/rules | jq '.data.groups[].rules[].name'

# Alertmanager config + status
curl -s http://127.0.0.1:9093/api/v2/status | jq '.versionInfo.version'
```

On a node:

```bash
docker ps | grep -E 'alloy|node_exporter|cadvisor'

# node_exporter metrics
curl -s http://127.0.0.1:9100/metrics | head
# cAdvisor metrics
curl -s http://127.0.0.1:8080/metrics | head
# Alloy UI (loopback only)
curl -s http://127.0.0.1:12345/  >/dev/null && echo "alloy ok"
```

Grafana: open `https://{{ grafana_domain }}` and log in with
`{{ grafana_admin_user }}` / your vault password. The Prometheus and Loki
datasources are already provisioned — verify under
**Connections → Data sources**.

Verify logs in Grafana: **Explore → Loki**, query `{job="docker"}` or
`{host="node01"}`.

## Troubleshooting

```bash
# Container logs
docker logs prometheus
docker logs loki
docker logs alertmanager
docker logs grafana
docker logs alloy      # on a node

# Recreate a service after a config edit (normally done by handlers automatically)
docker compose -f /opt/monitoring/docker-compose.yml up -d --force-recreate prometheus

# Reload Prometheus without restart
curl -X POST http://127.0.0.1:9090/-/reload

# Send a test Telegram message via Alertmanager
curl -X POST http://127.0.0.1:9093/api/v2/alerts \
  -H 'Content-Type: application/json' \
  -d '[{"labels":{"alertname":"TestAlert","severity":"warning","host":"node01"},"annotations":{"description":"manual test"},"startsAt":"2025-01-01T00:00:00Z"}]'

# Show what Ansible would change (dry-run)
ansible-playbook -i inventories/production/hosts.yml playbooks/deploy.yml --check --diff
```

### Common issues

- **Targets DOWN in Prometheus** — check the host firewall allows
  `grafana → node:9100/8080`, and that node_exporter/cAdvisor containers run.
- **No logs in Loki** — check Alloy can reach `<grafana_server>:3100`
  (`nodes → grafana` firewall) and `docker.sock` is mounted.
- **No Telegram alerts** — verify `telegram_bot_token`/`telegram_chat_id` in the
  vault; test with the curl above; check `docker logs alertmanager`.
- **cAdvisor shows no container CPU** — cgroup v2 requires `privileged: true`
  (already set). Confirm with `docker logs cadvisor`.
