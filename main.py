#!/usr/bin/env python3
"""
Agent Skills — a skills-based AI agent powered by a local LLM.

Settings are loaded from .env (see .env for all options).
CLI flags override .env values.

Usage:
    python main.py                                        # uses .env defaults
    python main.py --provider ollama --model llama3.1     # override via CLI
    python main.py --provider openai --url http://localhost:1234/v1

Commands inside chat:
    /skills     — list all available skills and their status
    /load NAME  — manually load a skill
    /reset      — clear conversation history
    /help       — show this help
    /quit       — exit
"""

import argparse
import logging
import uuid
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from core import Config, SkillManager, Agent, create_client

LOG_FILE = Path(__file__).parent / "agent_debug.log"

def _setup_logging():
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    logging.basicConfig(level=logging.DEBUG, handlers=[file_handler, console_handler])

_setup_logging()

console = Console()

SKILLS_DIR = Path(__file__).parent / "skills"


def parse_args(cfg: Config):
    parser = argparse.ArgumentParser(
        description="Skills-based AI Agent (Ollama / LM Studio / OpenAI-compat)"
    )
    parser.add_argument(
        "--provider",
        default=cfg.provider,
        help=f"LLM provider: ollama | openai (default from .env: {cfg.provider})",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name (overrides the provider-specific default from .env)",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Server base URL (overrides the provider-specific default from .env)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key for OpenAI-compatible providers",
    )
    parser.add_argument(
        "--skills-dir",
        default=cfg.skills_dir,
        help="Path to skills directory",
    )
    parser.add_argument(
        "--session-id",
        default="cli",
        help="Session id for conversation state (default: cli)",
    )
    parser.add_argument(
        "--new-session-per-run",
        action="store_true",
        help="Generate a new session id for each CLI launch",
    )
    return parser.parse_args()


def show_skills_table(skill_manager: SkillManager, active: dict):
    table = Table(title="Installed Skills", show_lines=True)
    table.add_column("Name", style="cyan bold")
    table.add_column("Description", style="white")
    table.add_column("Status", style="green")
    table.add_column("Tools", style="yellow")

    for name, skill in skill_manager.skills.items():
        status = "LOADED" if name in active else "available"
        tools = ""
        if skill.loaded and skill.tools:
            tools = ", ".join(t.name for t in skill.tools)
        table.add_row(name, skill.description[:80], status, tools)

    console.print(table)


def show_help():
    help_text = (
        "[bold cyan]Commands:[/]\n"
        "  [green]/skills[/]     — list all skills and their status\n"
        "  [green]/load NAME[/]  — manually load a skill\n"
        "  [green]/reset[/]      — clear conversation history\n"
        "  [green]/tools[/]      — show tools used in latest turn\n"
        "  [green]/help[/]       — show this help\n"
        "  [green]/quit[/]       — exit\n"
    )
    console.print(Panel(help_text, title="Help", border_style="blue"))


def main():
    cfg = Config.load()
    args = parse_args(cfg)

    provider = args.provider

    if provider == "ollama":
        base_url = args.url or cfg.ollama_base_url
        model = args.model or cfg.ollama_model
    else:
        base_url = args.url or cfg.openai_base_url
        model = args.model or cfg.openai_model

    api_key = args.api_key or cfg.openai_api_key

    client = create_client(
        provider,
        ollama_base_url=base_url,
        ollama_model=model,
        openai_base_url=base_url,
        openai_model=model,
        openai_api_key=api_key,
    )

    console.print(Panel(
        f"[bold]Agent Skills[/] — AI agent\n"
        f"Provider: [cyan]{provider}[/]  |  Model: [cyan]{model}[/]\n"
        f"Server:   [cyan]{base_url}[/]",
        title="Skills Agent",
        border_style="bright_blue",
    ))

    if not client.is_available():
        console.print(f"[bold red]Error:[/] Cannot connect to {base_url}")
        if provider == "ollama":
            console.print("Make sure Ollama is running: [cyan]ollama serve[/]")
        else:
            console.print("Make sure LM Studio server is started (or check your URL).")
        sys.exit(1)

    models = client.list_models()
    if models and model not in models:
        console.print(f"[bold yellow]Warning:[/] Model '{model}' not found on server.")
        console.print(f"Available: {', '.join(models[:15])}")
        if provider == "ollama":
            console.print(f"Pull it: [cyan]ollama pull {model}[/]")
        else:
            console.print("Check model name in LM Studio or your provider dashboard.")

    skill_manager = SkillManager(skills_dir=args.skills_dir, mcp_servers=cfg.mcp_servers)
    agent = Agent(client=client, skill_manager=skill_manager)
    session_id = f"cli-{uuid.uuid4().hex[:8]}" if args.new_session_per_run else args.session_id

    console.print(f"\nDiscovered [bold green]{len(skill_manager.skills)}[/] skills: "
                  f"{', '.join(skill_manager.get_skill_names())}")
    console.print(f"Session: [cyan]{session_id}[/]")
    console.print("Type [green]/help[/] for commands, or just start chatting.\n")

    while True:
        try:
            user_input = console.input("[bold green]You>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/]")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            cmd = user_input.split(maxsplit=1)
            command = cmd[0].lower()

            if command in ("/quit", "/exit", "/q"):
                console.print("[dim]Goodbye![/]")
                break
            elif command == "/help":
                show_help()
            elif command == "/skills":
                show_skills_table(skill_manager, agent.get_active_skills(session_id))
            elif command == "/load":
                if len(cmd) < 2:
                    console.print("[yellow]Usage: /load SKILL_NAME[/]")
                else:
                    session = agent.sessions.get_or_create(session_id)
                    result = agent._handle_load_skill(session, cmd[1])
                    agent.sessions.save(session)
                    console.print(f"[dim]{result}[/]")
            elif command == "/reset":
                agent.reset(session_id=session_id)
                console.print("[dim]Conversation reset.[/]")
            elif command == "/tools":
                called_tools = agent.get_last_tool_calls(session_id=session_id)
                if not called_tools:
                    console.print("[dim]No tools were called in the latest turn.[/]")
                else:
                    console.print("[dim]Latest tools:[/] " + ", ".join(called_tools))
            else:
                console.print(f"[yellow]Unknown command: {command}. Type /help[/]")
            continue

        with console.status("[bold cyan]Thinking...", spinner="dots"):
            try:
                response = agent.chat(user_input, session_id=session_id)
            except Exception as e:
                console.print(f"[bold red]Error:[/] {e}")
                continue

        console.print()
        try:
            console.print(Markdown(response))
        except Exception:
            console.print(response)
        console.print()


if __name__ == "__main__":
    main()
