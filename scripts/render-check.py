#!/usr/bin/env python3
"""Render every Jinja2 template with mock inventory vars and validate the
YAML ones. Catches indentation / undefined-var / Go-vs-Jinja conflicts that
ansible --syntax-check cannot."""
import sys
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from ansible.parsing.dataloader import DataLoader

# Mock inventory + vars mirroring group_vars and role defaults.
MOCK_VARS = {
    "monitoring_environment": "production",
    "monitoring_base_dir": "/opt/monitoring",
    "monitoring_agent_dir": "/opt/monitoring-agent",
    "monitoring_compose_project": "monitoring",
    "grafana_port": 3000,
    "prometheus_port": 9090,
    "loki_port": 3100,
    "alertmanager_port": 9093,
    "node_exporter_port": 9100,
    "cadvisor_port": 8080,
    "loki_retention_period": "30d",
    "grafana_server_address": "10.0.0.10",
    "loki_push_url": "http://10.0.0.10:3100/loki/api/v1/push",
    # grafana role defaults
    "grafana_image": "grafana/grafana:11.2.0",
    "prometheus_image": "prom/prometheus:v2.54.1",
    "loki_image": "grafana/loki:3.2.0",
    "alertmanager_image": "prom/alertmanager:v0.27.0",
    "grafana_bind_address": "0.0.0.0",
    "prometheus_bind_address": "127.0.0.1",
    "loki_bind_address": "0.0.0.0",
    "alertmanager_bind_address": "127.0.0.1",
    "prometheus_retention": "30d",
    "grafana_admin_user": "admin",
    "grafana_admin_password": "secret",
    "telegram_bot_token": "123:abc",
    "telegram_chat_id": "123456",
    # alloy role
    "alloy_image": "grafana/alloy:1.5.0",
    "alloy_listen_port": 12345,
    # node roles
    "node_exporter_image": "prom/node-exporter:v1.8.2",
    "cadvisor_image": "gcr.io/cadvisor/cadvisor:v0.49.1",
    # per-node context (for alloy config)
    "inventory_hostname": "node01",
    # groups + hostvars for prometheus.yml
    "groups": {
        "grafana": ["grafana01"],
        "nodes": ["node01", "node02", "node03"],
    },
    "hostvars": {
        "grafana01": {"ansible_host": "10.0.0.10"},
        "node01": {"ansible_host": "10.0.0.11"},
        "node02": {"ansible_host": "10.0.0.12"},
        "node03": {"ansible_host": "10.0.0.13"},
    },
}

# Templates: (role_dir, filename, is_yaml)
TEMPLATES = [
    ("roles/grafana/templates", "docker-compose.yml.j2", True),
    ("roles/grafana/templates", "prometheus.yml.j2", True),
    ("roles/grafana/templates", "loki-config.yml.j2", True),
    ("roles/grafana/templates", "alertmanager.yml.j2", True),
    ("roles/grafana/templates", "grafana-datasources.yml.j2", True),
    ("roles/alloy/templates", "config.alloy.j2", False),
    ("roles/alloy/templates", "docker-compose.yml.j2", True),
    ("roles/node_exporter/templates", "docker-compose.yml.j2", True),
    ("roles/cadvisor/templates", "docker-compose.yml.j2", True),
]

# Static files that are YAML (no Jinja): (path, name)
STATIC_YAML = [
    ("roles/grafana/files", "alerts.yml"),
]

loader = DataLoader()
errors = 0
for role_dir, name, is_yaml in TEMPLATES:
    env = Environment(loader=FileSystemLoader(role_dir), undefined=StrictUndefined,
                      keep_trailing_newline=True)
    try:
        rendered = env.get_template(name).render(**MOCK_VARS)
        print(f"RENDER OK: {role_dir}/{name}")
    except Exception as e:
        print(f"RENDER FAIL: {role_dir}/{name}: {e}")
        errors += 1
        continue
    if is_yaml:
        data = loader.load(rendered, None)
        if data is None:
            print(f"  YAML PARSE returned None: {role_dir}/{name}")
            errors += 1
        else:
            print(f"  YAML OK ({type(data).__name__})")
    # show first lines of rendered prometheus targets for sanity
    if name == "prometheus.yml.j2":
        for line in rendered.splitlines():
            if "10.0.0" in line or "targets" in line or "host:" in line:
                print(f"    {line}")

# Validate static YAML files (copied verbatim, no Jinja).
for role_dir, name in STATIC_YAML:
    path = f"{role_dir}/{name}"
    try:
        with open(path) as fh:
            rendered = fh.read()
    except OSError as e:
        print(f"READ FAIL: {path}: {e}")
        errors += 1
        continue
    data = loader.load(rendered, None)
    if data is None:
        print(f"YAML PARSE returned None: {path}")
        errors += 1
    else:
        print(f"STATIC YAML OK ({type(data).__name__}): {path}")

sys.exit(1 if errors else 0)
