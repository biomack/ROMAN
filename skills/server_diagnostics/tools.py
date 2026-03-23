import json
import platform
import re
import shutil
import socket
import subprocess
import time
from typing import Annotated, Optional

from core.tool_registry import tool


DEFAULT_COMMON_PORTS = [
    21, 22, 23, 25, 53, 80, 110, 123, 143, 443, 465, 587, 993, 995,
    1433, 1521, 3306, 3389, 5432, 6379, 8080, 8443, 9200, 27017
]


def _run_command(args: list[str], timeout: int = 20) -> dict:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
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


def _parse_ping_latency_ms(output: str) -> Optional[float]:
    patterns = [
        r"Average = (\d+)ms",
        r"avg = [\d\.]+/([\d\.]+)/",
        r"time[=<]\s*([\d\.]+)\s*ms",
    ]
    for pattern in patterns:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


@tool("Ping a host and return reachability and latency")
def ping_host(
    host: Annotated[str, "Hostname or IP address"],
    count: Annotated[int, "Number of ping packets"] = 4,
    timeout_seconds: Annotated[int, "Per-packet timeout in seconds"] = 3,
) -> str:
    system = platform.system().lower()
    if system == "windows":
        args = ["ping", "-n", str(count), "-w", str(timeout_seconds * 1000), host]
    else:
        args = ["ping", "-c", str(count), "-W", str(timeout_seconds), host]

    result = _run_command(args, timeout=max(10, count * timeout_seconds + 5))
    latency = _parse_ping_latency_ms(result["stdout"] + "\n" + result["stderr"])

    payload = {
        "host": host,
        "reachable": result["ok"],
        "latency_ms": latency,
        "raw_command": result["command"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool("Run traceroute/tracert to inspect path to host")
def traceroute_host(
    host: Annotated[str, "Hostname or IP address"],
    max_hops: Annotated[int, "Maximum route hops"] = 20,
) -> str:
    system = platform.system().lower()
    if system == "windows":
        args = ["tracert", "-d", "-h", str(max_hops), host]
    else:
        command = "traceroute"
        if shutil.which("traceroute") is None and shutil.which("tracepath") is not None:
            command = "tracepath"
            args = [command, host]
        else:
            args = [command, "-n", "-m", str(max_hops), host]

    result = _run_command(args, timeout=60)
    payload = {
        "host": host,
        "ok": result["ok"],
        "raw_command": result["command"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool("Check SSH TCP connectivity and optional login probe")
def test_ssh_connection(
    host: Annotated[str, "Hostname or IP address"],
    port: Annotated[int, "SSH port (default 22)"] = 22,
    username: Annotated[str, "Optional SSH username for probe"] = "",
    timeout_seconds: Annotated[int, "Connect timeout in seconds"] = 5,
    run_login_probe: Annotated[bool, "Run ssh command for auth probe"] = False,
) -> str:
    tcp_open = False
    tcp_latency_ms = None
    tcp_error = ""

    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            tcp_open = True
            tcp_latency_ms = round((time.perf_counter() - start) * 1000, 2)
    except OSError as exc:
        tcp_error = str(exc)

    login_probe = None
    if run_login_probe:
        if shutil.which("ssh") is None:
            login_probe = {
                "ok": False,
                "error": "ssh client not found in PATH",
            }
        else:
            target = f"{username}@{host}" if username else host
            args = [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                f"ConnectTimeout={timeout_seconds}",
                "-p",
                str(port),
                target,
                "exit",
            ]
            probe = _run_command(args, timeout=timeout_seconds + 5)
            login_probe = {
                "ok": probe["ok"],
                "returncode": probe["returncode"],
                "stdout": probe["stdout"],
                "stderr": probe["stderr"],
                "command": probe["command"],
            }

    payload = {
        "host": host,
        "port": port,
        "tcp_open": tcp_open,
        "tcp_latency_ms": tcp_latency_ms,
        "tcp_error": tcp_error,
        "login_probe": login_probe,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool("Scan common TCP ports and return open ones")
def scan_common_ports(
    host: Annotated[str, "Hostname or IP address"],
    timeout_seconds: Annotated[float, "TCP connect timeout per port"] = 0.8,
    ports: Annotated[list[int], "Optional custom list of ports to scan"] = None,
) -> str:
    if ports is None:
        ports = DEFAULT_COMMON_PORTS

    open_ports = []
    closed_or_filtered = 0

    for port in ports:
        started = time.perf_counter()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout_seconds)
                code = sock.connect_ex((host, int(port)))
                if code == 0:
                    open_ports.append(
                        {
                            "port": int(port),
                            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                        }
                    )
                else:
                    closed_or_filtered += 1
        except OSError:
            closed_or_filtered += 1

    payload = {
        "host": host,
        "scanned_count": len(ports),
        "open_ports": open_ports,
        "closed_or_filtered_count": closed_or_filtered,
        "ports_scanned": ports,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool("Run full diagnostics and return UP/PARTIAL/DOWN verdict")
def analyze_server_availability(
    host: Annotated[str, "Hostname or IP address"],
    ssh_port: Annotated[int, "SSH port to test"] = 22,
    ping_count: Annotated[int, "Ping packet count"] = 3,
    traceroute_max_hops: Annotated[int, "Max hops for traceroute"] = 20,
) -> str:
    ping_result = json.loads(ping_host(host=host, count=ping_count))
    trace_result = json.loads(traceroute_host(host=host, max_hops=traceroute_max_hops))
    ssh_result = json.loads(test_ssh_connection(host=host, port=ssh_port, run_login_probe=False))
    ports_result = json.loads(scan_common_ports(host=host))

    reachable = bool(ping_result.get("reachable")) or bool(ssh_result.get("tcp_open"))
    has_services = len(ports_result.get("open_ports", [])) > 0

    if reachable and has_services:
        verdict = "UP"
    elif reachable:
        verdict = "PARTIAL"
    else:
        verdict = "DOWN"

    payload = {
        "host": host,
        "verdict": verdict,
        "summary": {
            "ping_reachable": ping_result.get("reachable"),
            "ping_latency_ms": ping_result.get("latency_ms"),
            "ssh_tcp_open": ssh_result.get("tcp_open"),
            "open_ports": [port_info["port"] for port_info in ports_result.get("open_ports", [])],
            "traceroute_ok": trace_result.get("ok"),
        },
        "how_it_works": (
            "Verdict combines ping reachability/latency, traceroute path visibility, "
            "SSH TCP connectivity, and common TCP port scan results."
        ),
        "details": {
            "ping": ping_result,
            "traceroute": trace_result,
            "ssh": ssh_result,
            "ports": ports_result,
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
