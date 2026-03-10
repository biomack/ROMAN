"""
Tools for install_node_exporter skill.
Handles pre-checks, reachability, Ansible-based installation, and verification.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated, Any

from core.tool_registry import tool


NODE_EXPORTER_PORT = 9100
PLAYBOOK_PATH = Path(__file__).parent / "templates" / "install_node_exporter.yml"


def _run_command(args: list[str], timeout: int = 30, env: dict | None = None) -> dict:
    merged_env = {**os.environ, **(env or {})}
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            env=merged_env,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "command": " ".join(args),
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command not found: {args[0]}",
            "command": " ".join(args),
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": -2,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
            "command": " ".join(args),
        }


@tool("Parse user message and extract target servers, login, password for Node Exporter installation")
def collect_context(
    user_request: Annotated[str, "The user's request text to analyze"],
) -> str:
    """Parse user message and extract target servers, login, and password."""
    context: dict[str, Any] = {
        "original_request": user_request,
        "servers": [],
        "login": None,
        "password": None,
        "missing_fields": [],
    }

    ip_pattern = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    ips = re.findall(ip_pattern, user_request)

    hostname_pattern = r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b"
    hostnames = re.findall(hostname_pattern, user_request)
    hostnames = [h for h in hostnames if not re.match(ip_pattern, h)]

    context["servers"] = list(dict.fromkeys(ips + hostnames))

    login_patterns = [
        r"(?:логин|login|user|username|пользователь|юзер)\s*[=:\-—]\s*(\S+)",
        r"(?:логин|login|user|username|пользователь|юзер)\s+(\S+)",
    ]
    for pattern in login_patterns:
        match = re.search(pattern, user_request, re.IGNORECASE)
        if match:
            context["login"] = match.group(1).strip("\"'")
            break

    password_patterns = [
        r"(?:пароль|password|pass|pwd)\s*[=:\-—]\s*(\S+)",
        r"(?:пароль|password|pass|pwd)\s+(\S+)",
    ]
    for pattern in password_patterns:
        match = re.search(pattern, user_request, re.IGNORECASE)
        if match:
            context["password"] = match.group(1).strip("\"'")
            break

    if not context["servers"]:
        context["missing_fields"].append("servers")
    if not context["login"]:
        context["missing_fields"].append("login")
    if not context["password"]:
        context["missing_fields"].append("password")

    return json.dumps(context, ensure_ascii=False, indent=2)


@tool("Check if Node Exporter is already running on a server (curl to port 9100)")
def check_node_exporter(
    host: Annotated[str, "Server IP address or hostname"],
    port: Annotated[int, "Node Exporter port (default 9100)"] = NODE_EXPORTER_PORT,
    timeout_seconds: Annotated[int, "Connection timeout in seconds"] = 5,
) -> str:
    """Check if Node Exporter is already running on the target host."""
    running = False
    metrics_snippet = ""
    error = ""

    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            running = True
    except OSError as exc:
        error = str(exc)

    if running and shutil.which("curl"):
        result = _run_command(
            ["curl", "-s", "--max-time", str(timeout_seconds), f"http://{host}:{port}/metrics"],
            timeout=timeout_seconds + 3,
        )
        if result["ok"] and result["stdout"]:
            lines = result["stdout"].splitlines()[:5]
            metrics_snippet = "\n".join(lines)

    payload = {
        "host": host,
        "port": port,
        "running": running,
        "metrics_snippet": metrics_snippet,
        "error": error,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool("Verify server is reachable via SSH TCP and/or ping")
def check_server_reachable(
    host: Annotated[str, "Server IP address or hostname"],
    login: Annotated[str, "SSH username"] = "",
    password: Annotated[str, "SSH password"] = "",
    port: Annotated[int, "SSH port (default 22)"] = 22,
    timeout_seconds: Annotated[int, "Connection timeout in seconds"] = 5,
) -> str:
    """Verify that the server is reachable via SSH TCP connection and ping."""
    tcp_open = False
    tcp_error = ""
    ping_ok = False

    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            tcp_open = True
    except OSError as exc:
        tcp_error = str(exc)

    if shutil.which("ping"):
        import platform
        system = platform.system().lower()
        if system == "windows":
            args = ["ping", "-n", "2", "-w", str(timeout_seconds * 1000), host]
        else:
            args = ["ping", "-c", "2", "-W", str(timeout_seconds), host]
        result = _run_command(args, timeout=timeout_seconds * 3 + 5)
        ping_ok = result["ok"]

    reachable = tcp_open or ping_ok

    payload = {
        "host": host,
        "reachable": reachable,
        "ssh_tcp_open": tcp_open,
        "ssh_tcp_error": tcp_error,
        "ping_ok": ping_ok,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool("Run Ansible playbook to install Node Exporter on target servers")
def run_ansible_install(
    servers: Annotated[list[str], "List of server IPs or hostnames to install on"],
    login: Annotated[str, "SSH username for all servers"],
    password: Annotated[str, "SSH password for all servers"],
    ssh_port: Annotated[int, "SSH port (default 22)"] = 22,
    node_exporter_version: Annotated[str, "Node Exporter version to install (default 1.8.2)"] = "1.8.2",
) -> str:
    """Generate a temporary Ansible inventory and run the Node Exporter playbook."""
    if not shutil.which("ansible-playbook"):
        return json.dumps({
            "ok": False,
            "error": (
                "ansible-playbook not found in PATH. "
                "Install Ansible: pip install ansible"
            ),
        }, indent=2)

    if not PLAYBOOK_PATH.exists():
        return json.dumps({
            "ok": False,
            "error": f"Playbook not found: {PLAYBOOK_PATH}",
        }, indent=2)

    inventory_lines = ["[node_exporter_targets]"]
    for server in servers:
        inventory_lines.append(
            f"{server} ansible_port={ssh_port}"
        )
    inventory_lines.append("")
    inventory_lines.append("[node_exporter_targets:vars]")
    inventory_lines.append(f"ansible_user={login}")
    inventory_lines.append(f"ansible_ssh_pass={password}")
    inventory_lines.append("ansible_become=yes")
    inventory_lines.append("ansible_become_method=sudo")
    inventory_lines.append(f"ansible_become_pass={password}")
    inventory_lines.append("ansible_ssh_common_args=-o StrictHostKeyChecking=no")
    inventory_lines.append("")

    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="ne_install_")
        inventory_path = os.path.join(tmp_dir, "inventory.ini")
        with open(inventory_path, "w", encoding="utf-8") as f:
            f.write("\n".join(inventory_lines))

        args = [
            "ansible-playbook",
            "-i", inventory_path,
            str(PLAYBOOK_PATH),
            "-e", f"node_exporter_version={node_exporter_version}",
        ]

        timeout = 120 + 60 * len(servers)
        result = _run_command(args, timeout=timeout)

        payload = {
            "ok": result["ok"],
            "servers": servers,
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "command": result["command"],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            import shutil as _shutil
            _shutil.rmtree(tmp_dir, ignore_errors=True)


@tool("Post-install verification: check Node Exporter responds with valid metrics")
def verify_installation(
    host: Annotated[str, "Server IP address or hostname"],
    port: Annotated[int, "Node Exporter port (default 9100)"] = NODE_EXPORTER_PORT,
    timeout_seconds: Annotated[int, "Connection timeout in seconds"] = 10,
) -> str:
    """Check that Node Exporter responds on the expected port with valid metrics."""
    running = False
    healthy = False
    error = ""
    metrics_snippet = ""

    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            running = True
    except OSError as exc:
        error = str(exc)

    if running and shutil.which("curl"):
        result = _run_command(
            ["curl", "-s", "--max-time", str(timeout_seconds), f"http://{host}:{port}/metrics"],
            timeout=timeout_seconds + 3,
        )
        if result["ok"] and "node_" in result["stdout"]:
            healthy = True
            lines = result["stdout"].splitlines()[:10]
            metrics_snippet = "\n".join(lines)
        elif result["ok"]:
            metrics_snippet = result["stdout"][:500]
        else:
            error = result["stderr"] or "curl returned no output"

    payload = {
        "host": host,
        "port": port,
        "running": running,
        "healthy": healthy,
        "metrics_snippet": metrics_snippet,
        "error": error,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
