"""
Mattermost bot integration.

Connects to Mattermost via WebSocket, listens for messages in the
configured channel, passes them through the Agent, and replies in threads.

Includes a patched WebSocket class that fixes the SSL context bug
in mattermostdriver (uses SERVER_AUTH instead of CLIENT_AUTH).
"""

import asyncio
import json
import logging
import re
import ssl
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import websockets
from mattermostdriver import Driver
from mattermostdriver.websocket import Websocket as BaseWebsocket

from .agent import Agent

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


# ---------------------------------------------------------------------------
# WebSocket SSL fix for mattermostdriver
# ---------------------------------------------------------------------------

class _FixedWebsocket(BaseWebsocket):
    """WebSocket with correct SSL context (SERVER_AUTH for client connections)."""

    async def connect(self, event_handler):
        context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
        if not self.options["verify"]:
            context.verify_mode = ssl.CERT_NONE

        scheme = "wss://"
        if self.options["scheme"] != "https":
            scheme = "ws://"
            context = None

        url = "{scheme:s}{url:s}:{port:s}{basepath:s}/websocket".format(
            scheme=scheme,
            url=self.options["url"],
            port=str(self.options["port"]),
            basepath=self.options["basepath"],
        )

        self._alive = True

        while True:
            try:
                kw_args = {}
                if self.options["websocket_kw_args"] is not None:
                    kw_args = self.options["websocket_kw_args"]
                ws = await websockets.connect(url, ssl=context, **kw_args)
                await self._authenticate_websocket(ws, event_handler)
                while self._alive:
                    try:
                        await self._start_loop(ws, event_handler)
                    except websockets.ConnectionClosedError:
                        break
                if (not self.options["keepalive"]) or (not self._alive):
                    break
            except Exception as exc:
                logger.warning("WebSocket connection failed: %s", exc)
                await asyncio.sleep(self.options["keepalive_delay"])


# ---------------------------------------------------------------------------
# Mattermost Bot
# ---------------------------------------------------------------------------

class MattermostBot:
    """Runs the Agent as a Mattermost bot, responding in threads."""

    def __init__(
        self,
        agent: Agent,
        *,
        url: str,
        token: str,
        team: str,
        channel: str,
        bot_name: str = "",
        thread_history_depth: int = 20,
        scheme: str = "https",
        port: int = 443,
        verify: bool = True,
    ):
        self.agent = agent
        self.url = url
        self.token = token
        self.team = team
        self.channel = channel
        self.bot_name = bot_name.lstrip("@") if bot_name else ""
        self.thread_history_depth = max(0, thread_history_depth)
        self.scheme = scheme
        self.port = port
        self.verify = verify

        self._driver: Driver | None = None
        self._bot_user_id: str = ""
        self._channel_id: str = ""
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._mention_re: re.Pattern | None = None

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self):
        """Connect and start listening (blocking)."""
        if not self.token:
            raise RuntimeError(
                "MATTERMOST_TOKEN is not set. "
                "Set it in .env or pass via --mm-token."
            )

        self._driver = Driver({
            "url": self.url,
            "token": self.token,
            "scheme": self.scheme,
            "port": self.port,
            "verify": self.verify,
            "timeout": 30,
        })

        try:
            self._driver.login()
            self._bot_user_id = self._driver.client.userid
            logger.info("Mattermost bot connected, user_id=%s", self._bot_user_id)
            logger.info(
                "Thread history depth is set to %d message(s)",
                self.thread_history_depth,
            )

            if self.bot_name:
                self._mention_re = re.compile(
                    rf"@{re.escape(self.bot_name)}\b", re.IGNORECASE,
                )
                logger.info(
                    "Bot will only respond to messages mentioning @%s",
                    self.bot_name,
                )

            channel = self._driver.channels.get_channel_by_name_and_team_name(
                self.team, self.channel,
            )
            self._channel_id = channel["id"]
            logger.info(
                "Listening on channel %s (id=%s)", self.channel, self._channel_id,
            )

            handler = self._make_event_handler()
            self._driver.init_websocket(handler, websocket_cls=_FixedWebsocket)

        except KeyboardInterrupt:
            logger.info("Mattermost bot stopping (KeyboardInterrupt)...")
        finally:
            if self._driver:
                self._driver.disconnect()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _make_event_handler(self):
        async def _handler(message):
            try:
                data = json.loads(message) if isinstance(message, str) else message

                if data.get("event") != "posted":
                    return

                broadcast = data.get("broadcast", {})
                if broadcast.get("channel_id") != self._channel_id:
                    return

                event_data = data.get("data", {})
                post_str = event_data.get("post")
                if not post_str:
                    return

                post = json.loads(post_str) if isinstance(post_str, str) else post_str

                if post.get("user_id") == self._bot_user_id:
                    return

                message_text = post.get("message", "").strip()
                if not message_text:
                    return

                if self._mention_re:
                    mentioned = self._mention_re.search(message_text)
                    if not mentioned:
                        mentions_raw = event_data.get("mentions")
                        if mentions_raw:
                            try:
                                mention_ids = json.loads(mentions_raw) if isinstance(mentions_raw, str) else mentions_raw
                            except (json.JSONDecodeError, TypeError):
                                mention_ids = []
                            mentioned = self._bot_user_id in mention_ids
                        if not mentioned:
                            return

                if self._mention_re:
                    message_text = self._mention_re.sub("", message_text).strip()
                    if not message_text:
                        return

                root_id = post.get("root_id") or post.get("id")
                session_id = f"mm-{root_id}"

                logger.info(
                    "Received message from user=%s session=%s: %s",
                    post.get("user_id"), session_id, message_text[:200],
                )

                asyncio.ensure_future(
                    self._process_and_reply(
                        message_text,
                        session_id,
                        root_id,
                        post.get("id", ""),
                    )
                )

            except json.JSONDecodeError as exc:
                logger.debug("JSON parse error: %s", exc)
            except Exception as exc:
                logger.exception("Error parsing Mattermost event: %s", exc)

        return _handler

    async def _process_and_reply(
        self,
        message_text: str,
        session_id: str,
        root_id: str,
        current_post_id: str,
    ):
        """Run agent.chat in a thread and post the reply (background task)."""
        try:
            user_input = self._prepare_input_with_thread_history(
                message_text=message_text,
                session_id=session_id,
                root_id=root_id,
                current_post_id=current_post_id,
            )
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self._executor,
                self.agent.chat,
                user_input,
                session_id,
            )

            response = _THINK_RE.sub("", response).strip()
            if not response:
                logger.warning("Empty response after stripping <think> tags, skipping reply")
                return

            await loop.run_in_executor(
                self._executor,
                self._post_reply,
                response,
                root_id,
            )
        except Exception as exc:
            logger.exception(
                "Error processing message (session=%s): %s", session_id, exc,
            )

    def _prepare_input_with_thread_history(
        self,
        *,
        message_text: str,
        session_id: str,
        root_id: str,
        current_post_id: str,
    ) -> str:
        """
        Add previous thread messages to the current prompt.

        We do this only when the in-memory session is empty (for example, after
        process restart) to avoid duplicating already remembered context.
        """
        if self.thread_history_depth <= 0:
            return message_text

        session = self.agent.sessions.get_or_create(session_id)
        if session.messages:
            return message_text

        history_lines = self._fetch_thread_history_lines(
            root_id=root_id,
            current_post_id=current_post_id,
        )
        if not history_lines:
            return message_text

        logger.info(
            "Hydrated session=%s with %d historical thread message(s)",
            session_id,
            len(history_lines),
        )
        history_block = "\n".join(history_lines)
        return (
            "Контекст треда (предыдущие сообщения, от старых к новым):\n"
            f"{history_block}\n\n"
            "Текущее сообщение пользователя:\n"
            f"{message_text}"
        )

    def _fetch_thread_history_lines(
        self,
        *,
        root_id: str,
        current_post_id: str,
    ) -> list[str]:
        if not self._driver:
            return []

        try:
            thread_data = self._driver.posts.get_thread(root_id)
        except Exception as exc:
            logger.warning("Failed to load thread history for root_id=%s: %s", root_id, exc)
            return []

        posts = thread_data.get("posts")
        if not isinstance(posts, dict) or not posts:
            return []

        order = thread_data.get("order")
        if isinstance(order, list) and order:
            ordered_ids = [str(post_id) for post_id in order]
        else:
            ordered_ids = [
                str(post_id)
                for post_id, _ in sorted(
                    posts.items(),
                    key=lambda item: int(item[1].get("create_at", 0)) if isinstance(item[1], dict) else 0,
                )
            ]

        history_lines: list[str] = []
        for post_id in ordered_ids:
            post = posts.get(post_id)
            if not isinstance(post, dict):
                continue
            if post_id == current_post_id:
                continue

            text = re.sub(r"\s+", " ", str(post.get("message", "")).strip())
            if not text:
                continue

            role = self._mattermost_role_to_llm_role(post)
            history_lines.append(f"{role}: {text}")

        if self.thread_history_depth > 0:
            history_lines = history_lines[-self.thread_history_depth:]

        return history_lines

    def _mattermost_role_to_llm_role(self, post: dict[str, Any]) -> str:
        user_id = str(post.get("user_id", ""))
        if user_id and user_id == self._bot_user_id:
            return "assistant"
        return "user"

    def _post_reply(self, text: str, root_id: str):
        if not self._driver:
            return
        try:
            self._driver.posts.create_post(options={
                "channel_id": self._channel_id,
                "message": text,
                "root_id": root_id,
            })
            logger.info("Reply sent (root_id=%s, len=%d)", root_id, len(text))
        except Exception as exc:
            logger.exception(
                "Failed to post reply (root_id=%s): %s", root_id, exc,
            )
