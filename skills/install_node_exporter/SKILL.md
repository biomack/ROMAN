---
name: install-node-exporter
description: >
  Install Prometheus Node Exporter on remote Linux servers via Ansible.
  Requires server IPs/hostnames, SSH login and password from the user.
  Checks if Node Exporter is already running, verifies server reachability,
  and deploys using an Ansible playbook. Use when the user asks to install,
  deploy, or set up node_exporter, Node Exporter, or Prometheus host metrics agent.
---

# Install Node Exporter Skill

Use this skill when the user asks to install or deploy Prometheus Node Exporter on one or more servers.

## Required Input (must be provided by the user in chat)

| Parameter | Description |
|-----------|-------------|
| **servers** | One or more IP addresses or hostnames (space/comma separated) |
| **login** | SSH username for all target servers |
| **password** | SSH password for all target servers |

If any of these are missing, **ask the user before proceeding**. Do not guess credentials.

## Workflow

Copy this checklist and track progress:

```
Task Progress:
- [ ] Step 1: Parse input — extract servers, login, password
- [ ] Step 2: Pre-check — curl each server on port 9100
- [ ] Step 3: Reachability — verify unreachable servers via SSH
- [ ] Step 4: Install — run Ansible playbook on eligible servers
- [ ] Step 5: Verify — curl port 9100 on installed servers
- [ ] Step 6: Report results to user
```

### Step 1: Parse input

Call `collect_context` with the user's message.
If `missing_fields` is non-empty, ask the user for the missing data and **stop**.

### Step 2: Pre-check Node Exporter

Call `check_node_exporter` for **each** server.
- If the response shows `"running": true` — Node Exporter is already installed; skip this server and inform the user.
- If `"running": false` — proceed to Step 3.

### Step 3: Verify server reachability

Call `check_server_reachable` for each server that needs installation.
- If `"reachable": false` — report to the user that the server is unavailable and **skip** it.
- If `"reachable": true` — include the server in the installation list.

### Step 4: Install via Ansible

Call `run_ansible_install` with the list of reachable servers, login, and password.
The tool generates a temporary Ansible inventory and runs the playbook located at
`skills/install_node_exporter/templates/install_node_exporter.yml`.

### Step 5: Post-install verification

Call `check_node_exporter` again for every server where installation was attempted.
Report success or failure for each.

### Step 6: Final report

Present a summary table:

| Server | Status |
|--------|--------|
| 10.0.0.1 | Already installed |
| 10.0.0.2 | Installed successfully |
| 10.0.0.3 | Unreachable — skipped |
| 10.0.0.4 | Installation failed — see error |

## Available Tools

- `collect_context` — parse user message, extract servers/login/password
- `check_node_exporter` — curl server:9100/metrics to detect running exporter
- `check_server_reachable` — test SSH connectivity to the server
- `run_ansible_install` — execute the Ansible playbook for installation
- `verify_installation` — post-install check (curl + systemd status)

## Important Notes

- The playbook installs Node Exporter **1.8.2** as a systemd service on Linux.
- Default listen port is **9100**.
- If `ansible-playbook` is not found, inform the user that Ansible must be installed locally.
- Never store passwords in files; credentials are passed via environment variables and extra-vars.
