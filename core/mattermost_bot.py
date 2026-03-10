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
        scheme: str = "https",
        port: int = 443,
        verify: bool = True,
    ):
        self.agent = agent
        self.url = url
        self.token = token
        self.team = team
        self.channel = channel
        self.scheme = scheme
        self.port = port
        self.verify = verify

        self._driver: Driver | None = None
        self._bot_user_id: str = ""
        self._channel_id: str = ""
        self._executor = ThreadPoolExecutor(max_workers=4)

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

                root_id = post.get("root_id") or post.get("id")
                session_id = f"mm-{root_id}"

                logger.info(
                    "Received message from user=%s session=%s: %s",
                    post.get("user_id"), session_id, message_text[:200],
                )

                asyncio.ensure_future(
                    self._process_and_reply(message_text, session_id, root_id)
                )

            except json.JSONDecodeError as exc:
                logger.debug("JSON parse error: %s", exc)
            except Exception as exc:
                logger.exception("Error parsing Mattermost event: %s", exc)

        return _handler

    async def _process_and_reply(
        self, message_text: str, session_id: str, root_id: str,
    ):
        """Run agent.chat in a thread and post the reply (background task)."""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self._executor,
                self.agent.chat,
                message_text,
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
