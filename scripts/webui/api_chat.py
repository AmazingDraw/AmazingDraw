#!/usr/bin/env python3
"""Card chat history (readonly) and retired POST /api/chat."""

from __future__ import annotations
import sys
from pathlib import Path as _Path
for _p in [_Path(__file__).resolve().parent] + list(_Path(__file__).resolve().parent.parents):
    _native = _p / 'card_engine_core' / 'native'
    if _native.is_dir() and (
        list(_native.glob('card_asset_loader*.so'))
        or list(_native.glob('card_asset_loader*.pyd'))
    ):
        if str(_native) not in sys.path:
            sys.path.insert(0, str(_native))
        break


import json
from typing import Optional

from fastapi import APIRouter, HTTPException

from web_server import chat_history_file, webui_session_id

router = APIRouter(tags=["chat"])

_CHAT_GONE = "WebUI 已取消抽卡对话。请用直投或精选出卡。"


@router.get("/api/chat/history")
def get_chat_history(card_id: Optional[str] = None):
    hist_key = card_id or "home"
    items = []
    path = chat_history_file(hist_key)
    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    items.append(json.loads(line))
        except Exception as e:
            print(f"Error loading chat history from {path}: {e}")
    return {
        "card_id": card_id,
        "session_id": webui_session_id(card_id) if card_id else None,
        "messages": items[-200:],
    }


@router.post("/api/chat")
def chat_gone():
    raise HTTPException(status_code=410, detail=_CHAT_GONE)


@router.post("/api/chat/new")
def new_chat_gone():
    raise HTTPException(status_code=410, detail=_CHAT_GONE)


@router.get("/api/chat/sessions")
def sessions_gone():
    raise HTTPException(status_code=410, detail=_CHAT_GONE)
