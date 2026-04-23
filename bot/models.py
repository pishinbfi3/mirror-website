"""Pydantic models for Bale API messages and updates."""

from typing import Optional, Any, Dict
from datetime import datetime
from pydantic import BaseModel, Field


class User(BaseModel):
    id: int
    is_bot: bool
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None


class Chat(BaseModel):
    id: int
    type: str
    title: Optional[str] = None
    username: Optional[str] = None


class Document(BaseModel):
    file_id: str
    file_unique_id: str
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None


class Message(BaseModel):
    message_id: int
    from_: Optional[User] = Field(None, alias="from")
    chat: Chat
    date: datetime
    text: Optional[str] = None
    caption: Optional[str] = None
    document: Optional[Document] = None


class Update(BaseModel):
    update_id: int
    message: Optional[Message] = None
    edited_message: Optional[Message] = None
