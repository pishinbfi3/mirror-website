"""Async client for Bale Bot API."""

import asyncio
from typing import List, Optional, Any, Dict
from aiohttp import ClientSession, ClientTimeout, FormData

from .config import BotConfig
from .exceptions import APIError
from .logger import get_logger
from .models import Update

logger = get_logger(__name__)


class BaleAPIClient:
    """Handles all HTTP calls to Bale API asynchronously."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.base_url = str(config.api_base_url).rstrip("/")
        self.bot_url = f"{self.base_url}/bot{config.bot_token}"
        self.timeout = ClientTimeout(total=config.api_timeout)
        self._session: Optional[ClientSession] = None

    async def __aenter__(self):
        self._session = ClientSession(
            timeout=self.timeout,
            headers={"User-Agent": "Bale-SSH-Bot/2.0", "Accept": "application/json"},
        )
        return self

    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()

    async def _post(self, method: str, data: Optional[Dict] = None) -> Dict:
        """Send POST request to a Bale API method."""
        if not self._session:
            raise APIError("Client session not initialized")
        url = f"{self.bot_url}/{method}"
        try:
            async with self._session.post(url, json=data) as resp:
                result = await resp.json()
                if not result.get("ok"):
                    raise APIError(f"API error: {result}")
                return result
        except Exception as e:
            logger.error(f"POST {method} failed: {e}")
            raise APIError(f"Request failed: {e}") from e

    async def _get(self, method: str, params: Optional[Dict] = None) -> Dict:
        """Send GET request."""
        if not self._session:
            raise APIError("Client session not initialized")
        url = f"{self.bot_url}/{method}"
        try:
            async with self._session.get(url, params=params) as resp:
                result = await resp.json()
                if not result.get("ok"):
                    raise APIError(f"API error: {result}")
                return result
        except Exception as e:
            logger.error(f"GET {method} failed: {e}")
            raise APIError(f"Request failed: {e}") from e

    async def get_updates(
        self, offset: Optional[int] = None, timeout: int = 30, limit: int = 10
    ) -> List[Update]:
        """Long-poll for new updates."""
        params = {"timeout": timeout, "limit": limit}
        if offset is not None:
            params["offset"] = offset
        data = await self._get("getUpdates", params=params)
        return [Update(**u) for u in data.get("result", [])]

    async def send_message(
        self, chat_id: str, text: str, reply_to_message_id: Optional[int] = None
    ) -> None:
        """Send a plain text message (Markdown optional but safe)."""
        payload = {"chat_id": chat_id, "text": text}
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        # Try with Markdown first, fallback to plain text
        payload["parse_mode"] = "Markdown"
        try:
            await self._post("sendMessage", data=payload)
        except APIError:
            payload["parse_mode"] = None
            await self._post("sendMessage", data=payload)

    async def send_document(
        self, chat_id: str, file_path: str, caption: Optional[str] = None
    ) -> None:
        """Upload a file as a document."""
        if not self._session:
            raise APIError("Client session not initialized")
        url = f"{self.bot_url}/sendDocument"
        data = FormData()
        data.add_field("chat_id", chat_id)
        if caption:
            data.add_field("caption", caption)
        with open(file_path, "rb") as f:
            data.add_field("document", f, filename=file_path.split("/")[-1])
            async with self._session.post(url, data=data) as resp:
                result = await resp.json()
                if not result.get("ok"):
                    raise APIError(f"Document send failed: {result}")

    async def get_file(self, file_id: str) -> str:
        """Get file path from file_id and return full download URL."""
        data = await self._get("getFile", params={"file_id": file_id})
        file_path = data["result"]["file_path"]
        return f"{self.base_url}/file/bot{self.config.bot_token}/{file_path}"

    async def send_chat_action(self, chat_id: str, action: str = "typing") -> None:
        """Send chat action (typing, upload_document, etc.)."""
        await self._post("sendChatAction", data={"chat_id": chat_id, "action": action})
