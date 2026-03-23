---
name: install-node-exporter
description: >
  Install Prometheus Node Exporter on remote Linux servers via Ansible.
  Requires server IPs/hostnames, SSH login and password from the user.
  Checks if Node Exporter is already running, verifies server reachability,
  and deploys using an Ansible playbook. Use this skill whenever the user asks
  to install, deploy, set up, or configure node_exporter, Node Exporter,
  or a Prometheus host metrics agent — even if they just say "add monitoring
  to these servers" or "set up metrics collection."
---

# Install Node Exporter Skill

Deploy Prometheus Node Exporter on one or more Linux servers.

## Required input

| Parameter | Description |
|-----------|-------------|
| **servers** | One or more IP addresses or hostnames (space/comma separated) |
| **login** | SSH username for all target servers |
| **password** | SSH password for all target servers |

If any of these are missing, ask the user before proceeding. Never guess credentials.

## Workflow

Track progress through each step:

### Step 1 — Parse input
Call `collect_context` with the user's message.
If `missing_fields` is non-empty, ask the user for the missing data and stop.

### Step 2 — Pre-check Node Exporter
Call `check_node_exporter` for each server.
If `"running": true`, Node Exporter is already installed — skip and inform the user.
If `"running": false`, continue to Step 3.

### Step 3 — Verify reachability
Call `check_server_reachable` for each server that needs installation.
If `"reachable": false`, report the server as unavailable and skip it.
If `"reachable": true`, include it in the installation list.

### Step 4 — Install via Ansible
Call `run_ansible_install` with the list of reachable servers, login, and password.
The playbook is located at `assets/install_node_exporter.yml`.

### Step 5 — Post-install verification
Call `verify_installation` for every server where installation was attempted.
Report success or failure for each.

### Step 6 — Final report
Present a summary table:

| Server | Status |
|--------|--------|
| 10.0.0.1 | Already installed |
| 10.0.0.2 | Installed successfully |
| 10.0.0.3 | Unreachable — skipped |
| 10.0.0.4 | Installation failed — see error |

## Important notes

- The playbook installs Node Exporter **1.8.2** as a systemd service on Linux.
- Default listen port is **9100**.
- If `ansible-playbook` is not found, inform the user that Ansible must be installed locally.
- Never store passwords in files; credentials are passed via environment variables and extra-vars.
