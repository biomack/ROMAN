"""
Agent engine with dynamic skill loading and tool‑calling loop.

Flow:
1. System prompt includes the skill catalog (name + description only).
2. The LLM can call `load_skill` to activate a skill → full SKILL.md
   instructions are injected into context and skill tools become available.
3. The LLM can call any tool from active skills.
4. Loop continues until the LLM produces a final text response.
"""

import json
import logging
import re

from .llm_client import LLMClient
from .skill_manager import SkillManager, Skill
from .session_store import InMemorySessionStore, SessionData

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 15

SYSTEM_TEMPLATE = """\
You are a helpful AI assistant with a dynamic skills system.
You can load specialized skills to gain new capabilities on demand.

## Available Skills (not yet loaded – call `load_skill` to activate)
{catalog}

## Rules
1. When a user's request matches a skill, call `load_skill` first to get full instructions and tools.
2. After loading, follow the skill's instructions and use its tools.
3. You may load multiple skills if the task requires it.
4. If no skill is relevant, answer using your general knowledge.
5. Always respond to the user in the same language they use.
6. If any skill workflow is started, call `collect_context` before all other workflow tools.
7. If `collect_context` reports missing_fields, ask a clarifying question and stop.

{active_section}
"""


class Agent:
    def __init__(
        self,
        client: LLMClient,
        skill_manager: SkillManager,
        temperature: float = 0.4,
        session_store: InMemorySessionStore | None = None,
    ):
        self.client = client
        self.skills = skill_manager
        self.temperature = temperature
        self.sessions = session_store or InMemorySessionStore()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(self, user_message: str, session_id: str = "default", metadata: dict | None = None) -> str:
        session = self.sessions.get_or_create(session_id)
        session.messages.append({"role": "user", "content": user_message})
        session.session_state["last_metadata"] = metadata or {}
        session.session_state["context_collected_for_turn"] = False
        session.session_state["last_tool_calls"] = []
        response = self._run_loop(session)
        self.sessions.save(session)
        return response

    def reset(self, session_id: str = "default"):
        self.sessions.reset(session_id)

    def get_active_skills(self, session_id: str = "default") -> dict[str, Skill]:
        session = self.sessions.get_or_create(session_id)
        return session.active_skills

    def get_last_tool_calls(self, session_id: str = "default") -> list[str]:
        session = self.sessions.get_or_create(session_id)
        calls = session.session_state.get("last_tool_calls", [])
        return list(calls) if isinstance(calls, list) else []

    # ------------------------------------------------------------------
    # Agent loop
    # ------------------------------------------------------------------

    def _run_loop(self, session: SessionData) -> str:
        for round_num in range(MAX_TOOL_ROUNDS):
            tools = self._collect_tools(session)
            system = self._build_system_prompt(session)

            logger.info(
                "=== Round %d | active_skills=%s | tools_count=%d ===",
                round_num, list(session.active_skills.keys()), len(tools),
            )
            logger.debug("System prompt (%d chars):\n%s", len(system), system)
            logger.debug(
                "Messages history (%d msgs): %s",
                len(session.messages),
                json.dumps(
                    [{"role": m["role"], "content": (m.get("content") or "")[:120]}
                     for m in session.messages],
                    ensure_ascii=False,
                ),
            )

            response = self.client.chat(
                messages=[{"role": "system", "content": system}] + session.messages,
                tools=tools,
                temperature=self.temperature,
            )
            msg = response.get("message", {})

            tool_calls = msg.get("tool_calls")
            if tool_calls:
                logger.info(
                    "LLM requested %d tool call(s): %s",
                    len(tool_calls),
                    [tc["function"]["name"] for tc in tool_calls],
                )
                if msg.get("content"):
                    logger.debug("LLM thinking text: %s", msg["content"][:500])

                session.messages.append({
                    "role": "assistant",
                    "content": msg.get("content", ""),
                    "tool_calls": tool_calls,
                })
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    fn_args = tc["function"].get("arguments", {})
                    logger.info(
                        "Calling tool: %s(%s)",
                        fn_name,
                        json.dumps(fn_args, ensure_ascii=False)[:500],
                    )

                    result, should_stop = self._execute_tool(session, tc)
                    logger.info("Tool result [%s] (len=%d): %s", fn_name, len(result), result[:500])

                    session.messages.append({
                        "role": "tool",
                        "content": result,
                        "tool_call_id": tc.get("id", ""),
                    })
                    if should_stop:
                        question = self._extract_clarifying_question(result)
                        logger.info("Stopping loop: clarification needed — %s", question[:300])
                        session.messages.append({"role": "assistant", "content": question})
                        return question
            else:
                content = msg.get("content", "")
                logger.info("LLM final response (len=%d): %s", len(content), content[:500])
                session.messages.append({"role": "assistant", "content": content})
                return content

        logger.warning("Agent reached MAX_TOOL_ROUNDS=%d without final answer", MAX_TOOL_ROUNDS)
        return "[Agent reached maximum tool-call rounds]"

    # ------------------------------------------------------------------
    # System prompt (rebuilt each turn to reflect active skills)
    # ------------------------------------------------------------------

    def _build_system_prompt(self, session: SessionData) -> str:
        catalog_lines = []
        for name, skill in self.skills.skills.items():
            status = " [LOADED]" if name in session.active_skills else ""
            catalog_lines.append(f"  - {name}: {skill.description}{status}")
        catalog = "\n".join(catalog_lines) if catalog_lines else "No skills installed."

        active_section = ""
        if session.active_skills:
            parts = []
            for name, skill in session.active_skills.items():
                tool_names = [t.name for t in skill.tools]
                tools_str = ", ".join(tool_names) if tool_names else "none"
                parts.append(
                    f"### Skill: {name}\n"
                    f"Tools: {tools_str}\n\n"
                    f"{skill.instructions}"
                )
                for fname, fcontent in skill.extra_files.items():
                    parts.append(f"#### Reference file: {fname}\n{fcontent}")
            active_section = "## Active Skills (loaded)\n\n" + "\n\n---\n\n".join(parts)

        return SYSTEM_TEMPLATE.format(catalog=catalog, active_section=active_section)

    # ------------------------------------------------------------------
    # Tool management
    # ------------------------------------------------------------------

    def _collect_tools(self, session: SessionData) -> list[dict]:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "load_skill",
                    "description": (
                        "Load a skill by name to gain its instructions and tools. "
                        "Call this before using a skill's capabilities."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {
                                "type": "string",
                                "description": "Exact name of the skill to load",
                            }
                        },
                        "required": ["skill_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "create_new_skill",
                    "description": (
                        "Create a brand-new reusable skill from the current experience. "
                        "Use this to save a successful approach as a skill for future use."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Skill name (lowercase, underscores)",
                            },
                            "description": {
                                "type": "string",
                                "description": "What the skill does and when to use it",
                            },
                            "instructions": {
                                "type": "string",
                                "description": "Detailed markdown instructions for the skill",
                            },
                            "tools_code": {
                                "type": "string",
                                "description": "Optional Python code for skill tools (tools.py content)",
                            },
                        },
                        "required": ["name", "description", "instructions"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "collect_context",
                    "description": (
                        "Normalize user input into structured JSON and detect missing fields. "
                        "Must be called as the first step in skill workflows."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "Raw user message text",
                            },
                            "metadata": {
                                "type": "object",
                                "description": "Optional metadata object",
                            },
                        },
                        "required": ["text"],
                    },
                },
            },
        ]

        for skill in session.active_skills.values():
            for tool in skill.tools:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                })
        return tools

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _execute_tool(self, session: SessionData, tool_call: dict) -> tuple[str, bool]:
        func_name = tool_call["function"]["name"]
        raw_args = tool_call["function"].get("arguments", {})
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        session.session_state.setdefault("last_tool_calls", []).append(func_name)

        if (
            session.active_skills
            and func_name not in {"collect_context", "load_skill", "create_new_skill"}
            and not session.session_state.get("context_collected_for_turn")
        ):
            return (
                "Workflow requires `collect_context` first. "
                "Call collect_context with the latest user text before other tools.",
                False,
            )

        if func_name == "load_skill":
            return self._handle_load_skill(session, args.get("skill_name", "")), False

        if func_name == "create_new_skill":
            return self._handle_create_skill(args), False

        if func_name == "collect_context":
            text = args.get("text", "")
            if not text:
                text = self._latest_user_text(session)
            metadata = args.get("metadata")
            if metadata is None:
                metadata = session.session_state.get("last_metadata", {})
            result = self._collect_context(
                text=text,
                metadata=metadata,
            )
            session.session_state["context_collected_for_turn"] = True
            return result, self._has_missing_fields(result)

        for skill in session.active_skills.values():
            for tool in skill.tools:
                if tool.name == func_name:
                    try:
                        return str(tool.function(**args)), False
                    except Exception as e:
                        return f"Error in {func_name}: {e}", False

        if func_name in self.skills.skills:
            load_result = self._handle_load_skill(session, func_name)
            return (
                f"Auto-loaded skill '{func_name}'. {load_result}\n"
                f"Now call the skill's specific tools (not the skill name)."
            ), False

        return f"Unknown tool: {func_name}", False

    def _handle_load_skill(self, session: SessionData, skill_name: str) -> str:
        logger.info("Loading skill '%s'...", skill_name)
        skill = self.skills.load_skill(skill_name)
        if skill is None:
            available = ", ".join(self.skills.get_skill_names())
            logger.warning("Skill '%s' not found. Available: %s", skill_name, available)
            return f"Skill '{skill_name}' not found. Available: {available}"

        if skill.name in session.active_skills:
            logger.debug(
                "Skill '%s' already loaded (requested as '%s'), skipping",
                skill.name,
                skill_name,
            )
            return f"Skill '{skill.name}' is already loaded."

        session.active_skills[skill.name] = skill
        tool_names = [t.name for t in skill.tools]
        extra = list(skill.extra_files.keys())
        logger.info(
            "Skill '%s' loaded — tools: %s, extra_files: %s",
            skill.name,
            tool_names,
            extra,
        )
        return (
            f"Skill '{skill.name}' loaded successfully.\n"
            f"Tools now available: {tool_names}\n"
            f"Extra reference files: {extra}\n"
            f"Instructions have been added to your system context."
        )

    def _handle_create_skill(self, args: dict) -> str:
        return self.skills.create_skill(
            name=args.get("name", "unnamed"),
            description=args.get("description", ""),
            instructions=args.get("instructions", ""),
            tools_code=args.get("tools_code", ""),
        )

    @staticmethod
    def _collect_context(text: str, metadata: dict | None = None) -> str:
        metadata = metadata or {}
        normalized_text = re.sub(r"\s+", " ", (text or "").strip())
        missing_fields: list[str] = []
        warnings: list[str] = []

        if not normalized_text:
            missing_fields.append("user_intent")
        if len(normalized_text) < 8:
            missing_fields.append("task_details")
        if "?" in normalized_text and "please" not in normalized_text.lower():
            warnings.append("Request may be ambiguous; consider adding target/output format.")
        if metadata and not isinstance(metadata, dict):
            warnings.append("Metadata should be an object.")

        clarifying_question = ""
        if missing_fields:
            clarifying_question = (
                "Please уточните запрос: не хватает полей "
                f"{', '.join(missing_fields)}. "
                "Что именно нужно сделать и какой результат ожидаете?"
            )

        return json.dumps(
            {
                "normalized": {"text": normalized_text, "metadata": metadata},
                "missing_fields": missing_fields,
                "clarifying_question": clarifying_question,
                "warnings": warnings,
            },
            ensure_ascii=False,
            indent=2,
        )

    @staticmethod
    def _has_missing_fields(collect_context_result: str) -> bool:
        try:
            payload = json.loads(collect_context_result)
        except Exception:
            return False
        return bool(payload.get("missing_fields"))

    @staticmethod
    def _extract_clarifying_question(collect_context_result: str) -> str:
        default_question = "Нужны уточнения по задаче. Пожалуйста, добавьте недостающие детали."
        try:
            payload = json.loads(collect_context_result)
        except Exception:
            return default_question
        return payload.get("clarifying_question") or default_question

    @staticmethod
    def _latest_user_text(session: SessionData) -> str:
        for message in reversed(session.messages):
            if message.get("role") == "user":
                return str(message.get("content", ""))
        return ""
