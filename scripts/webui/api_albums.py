"""WebUI 相册：专辑索引落在 ~/.amazingdraw/albums.json，不进 card.json。"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

import amazingdraw_paths

router = APIRouter(tags=["albums"])

_LOCK = threading.Lock()
FINISHED_STATUSES = {"rendered", "delivered", "success"}
VIRTUAL_IDS = {"all", "unfiled"}
FAVORITES_ID = "favorites"
FAVORITES_NAME = "我的收藏"
RESERVED_ALBUM_NAMES = {FAVORITES_NAME, "收藏"}
PERSON_OTHER = "__other__"
PERSON_MAIN_MIN = 3
SKIP_PERSON_LABELS = {"ComfyUI"}
PERSON_TEACHER_MARKERS = ("老师", "教师", "班主任", "教官")
# 相册侧栏合并用，不改 card.json。点「高中生」会带上 JK / 女高中生 等别名。
PERSON_ALIAS_GROUPS = {
    "高中生": ("jk", "j.k.", "ｊｋ", "jk少女", "jk女友", "jk学生", "jk制服", "高中生", "女高中生", "女子高中生", "高中女生", "高中少女", "神秘女生"),
    "初中生": ("jc", "j.c.", "ｊｃ", "jc少女", "jc女友", "jc学生", "初中生", "女初中生", "初中女生", "初中少女", "女子初中生", "神秘少女"),
    "孕妇": ("孕妇", "小孕妇", "孕妈", "怀孕", "孕期"),
}


def albums_path() -> Path:
    return amazingdraw_paths.albums_file()


def _empty_store() -> dict:
    return {"version": 1, "albums": []}


def _load_store() -> dict:
    path = albums_path()
    albums: List[Any] = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = None
        if isinstance(data, dict) and isinstance(data.get("albums"), list):
            albums = data.get("albums") or []
    cleaned = []
    for raw in albums:
        item = _normalize_album(raw)
        if item:
            cleaned.append(item)
    store = {"version": 1, "albums": cleaned}
    if _ensure_favorites(store):
        _save_store(store)
    return store


def _favorites_template(now: Optional[int] = None) -> dict:
    stamp = int(now or time.time())
    return {
        "id": FAVORITES_ID,
        "name": FAVORITES_NAME,
        "system": True,
        "cover_card_id": "",
        "created_at": stamp,
        "updated_at": stamp,
        "card_ids": [],
    }


def _ensure_favorites(store: dict) -> bool:
    albums = list(store.get("albums") or [])
    found = next((item for item in albums if item.get("id") == FAVORITES_ID), None)
    if found is None:
        store["albums"] = [_favorites_template()] + albums
        return True
    found["name"] = FAVORITES_NAME
    found["system"] = True
    rest = [item for item in albums if item.get("id") != FAVORITES_ID]
    store["albums"] = [found] + rest
    return False


def _normalize_album(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    album_id = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    if not album_id or not name or album_id in VIRTUAL_IDS:
        return None
    system = album_id == FAVORITES_ID or bool(raw.get("system"))
    if album_id == FAVORITES_ID:
        name = FAVORITES_NAME
    ids: List[str] = []
    seen = set()
    for item in raw.get("card_ids") or []:
        cid = str(item or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        ids.append(cid)
    cover = str(raw.get("cover_card_id") or "").strip()
    if cover and cover not in seen:
        cover = ids[0] if ids else ""
    now = int(time.time())
    try:
        created = int(raw.get("created_at") or now)
    except (TypeError, ValueError):
        created = now
    try:
        updated = int(raw.get("updated_at") or created)
    except (TypeError, ValueError):
        updated = created
    return {
        "id": album_id,
        "name": FAVORITES_NAME if system and album_id == FAVORITES_ID else name[:80],
        "system": system,
        "cover_card_id": cover,
        "created_at": created,
        "updated_at": updated,
        "card_ids": ids,
    }


def _save_store(store: dict) -> None:
    path = albums_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"version": 1, "albums": store.get("albums") or []},
        ensure_ascii=False,
        indent=2,
    )
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _find_album(store: dict, album_id: str) -> dict:
    for album in store.get("albums") or []:
        if album.get("id") == album_id:
            return album
    raise HTTPException(status_code=404, detail="专辑不存在")


def _public_album(album: dict) -> dict:
    ids = list(album.get("card_ids") or [])
    cover = str(album.get("cover_card_id") or "")
    if not cover and ids:
        cover = ids[0]
    return {
        "id": album["id"],
        "name": album["name"],
        "system": bool(album.get("system") or album.get("id") == FAVORITES_ID),
        "cover_card_id": cover,
        "created_at": album.get("created_at"),
        "updated_at": album.get("updated_at"),
        "card_ids": ids,
        "count": len(ids),
    }


def prune_card_from_albums(card_id: str) -> None:
    cid = str(card_id or "").strip()
    if not cid:
        return
    with _LOCK:
        store = _load_store()
        changed = False
        for album in store.get("albums") or []:
            ids = album.get("card_ids") or []
            if cid not in ids:
                continue
            album["card_ids"] = [x for x in ids if x != cid]
            if album.get("cover_card_id") == cid:
                album["cover_card_id"] = (album["card_ids"][0] if album["card_ids"] else "")
            album["updated_at"] = int(time.time())
            changed = True
        if changed:
            _save_store(store)


def prune_cards_from_albums(card_ids: List[str]) -> None:
    for cid in card_ids or []:
        prune_card_from_albums(cid)


def _has_image(card: dict) -> bool:
    return bool(card.get("image_url") or card.get("render_image"))


def _in_default_pool(card: dict, include_unrendered: bool) -> bool:
    if include_unrendered:
        return True
    status = str(card.get("status") or "")
    return status in FINISHED_STATUSES and _has_image(card)


def _month_key(mtime: Any) -> str:
    try:
        ts = float(mtime)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    return time.strftime("%Y-%m", time.localtime(ts))


def _all_cards() -> List[dict]:
    from api_cards import list_cards
    cards = list_cards()
    return cards if isinstance(cards, list) else []


def _looks_like_label(name: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in name)


def _norm_person_token(name: str) -> str:
    text = str(name or "").strip().lower()
    return "".join(ch for ch in text if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff"))


def _build_person_alias_index() -> Dict[str, str]:
    index: Dict[str, str] = {}
    for canon, aliases in PERSON_ALIAS_GROUPS.items():
        index[_norm_person_token(canon)] = canon
        for alias in aliases:
            key = _norm_person_token(alias)
            if key:
                index[key] = canon
    return index


_PERSON_ALIAS_INDEX = _build_person_alias_index()


def _latin_school_tag(key: str, tag: str) -> bool:
    if key == tag:
        return True
    if key.startswith(tag) and len(key) > len(tag):
        return not key[len(tag)].isascii()
    return False


def canon_person(name: str) -> str:
    raw = str(name or "").strip()
    if not raw or raw in SKIP_PERSON_LABELS:
        return raw
    key = _norm_person_token(raw)
    if key in _PERSON_ALIAS_INDEX:
        return _PERSON_ALIAS_INDEX[key]
    if any(mark in raw for mark in PERSON_TEACHER_MARKERS):
        return raw
    if _latin_school_tag(key, "jk"):
        return "高中生"
    if _latin_school_tag(key, "jc"):
        return "初中生"
    if "孕妇" in raw or "怀孕" in raw or "孕期" in raw:
        return "孕妇"
    if "初中" in raw:
        return "初中生"
    if "高中" in raw:
        return "高中生"
    return raw


def _group_counts(cards: List[dict], field: str, *, require_cjk: bool = False) -> List[dict]:
    counts: Dict[str, int] = {}
    aliases: Dict[str, set] = {}
    for card in cards:
        raw = str(card.get(field) or "").strip()
        if not raw:
            continue
        name = raw
        if field == "person":
            name = canon_person(raw)
            if not name or name in SKIP_PERSON_LABELS:
                continue
            if raw != name:
                aliases.setdefault(name, set()).add(raw)
        elif require_cjk and not _looks_like_label(name):
            continue
        counts[name] = counts.get(name, 0) + 1
    rows = []
    for name, count in counts.items():
        row: Dict[str, Any] = {"name": name, "count": count}
        extra = sorted(aliases.get(name) or [])
        if extra:
            row["aliases"] = extra
        rows.append(row)
    rows.sort(key=lambda item: (-int(item["count"]), str(item["name"])))
    return rows


def _filter_pool(
    cards: List[dict],
    *,
    album_id: str,
    store: dict,
    month: str,
    person: str,
    scene: str,
    theme: str,
    include_unrendered: bool,
) -> List[dict]:
    pooled = [c for c in cards if _in_default_pool(c, include_unrendered)]
    filed: set = set()
    album_set: Optional[set] = None
    if album_id == "unfiled":
        for album in store.get("albums") or []:
            filed.update(album.get("card_ids") or [])
    elif album_id and album_id not in VIRTUAL_IDS:
        album = _find_album(store, album_id)
        album_set = set(album.get("card_ids") or [])

    person_rows = _group_counts(pooled, "person")
    rare_persons = {
        row["name"] for row in person_rows if int(row["count"]) < PERSON_MAIN_MIN
    }

    out = []
    for card in pooled:
        cid = str(card.get("card_id") or "")
        if album_id == "unfiled" and cid in filed:
            continue
        if album_set is not None and cid not in album_set:
            continue
        if month and month != "all" and _month_key(card.get("mtime")) != month:
            continue
        card_person = canon_person(str(card.get("person") or "").strip())
        if person == PERSON_OTHER:
            if card_person not in rare_persons:
                continue
        elif person:
            want = canon_person(person)
            if card_person != want:
                continue
        if scene and str(card.get("scene") or "") != scene:
            continue
        if theme and str(card.get("theme") or "") != theme:
            continue
        out.append(card)
    return out


def _facets(cards: List[dict]) -> dict:
    persons = sorted({str(c.get("person") or "").strip() for c in cards if str(c.get("person") or "").strip()})
    scenes = sorted({str(c.get("scene") or "").strip() for c in cards if str(c.get("scene") or "").strip()})
    themes = sorted({str(c.get("theme") or "").strip() for c in cards if str(c.get("theme") or "").strip()})
    months = sorted(
        {key for key in (_month_key(c.get("mtime")) for c in cards) if key},
        reverse=True,
    )
    return {"persons": persons, "scenes": scenes, "themes": themes, "months": months}


@router.get("/api/albums")
def list_albums():
    with _LOCK:
        store = _load_store()
    cards = _all_cards()
    pool = [c for c in cards if _in_default_pool(c, False)]
    filed = set()
    for album in store.get("albums") or []:
        filed.update(album.get("card_ids") or [])
    unfiled = [c for c in pool if str(c.get("card_id") or "") not in filed]
    return {
        "albums": [_public_album(a) for a in store.get("albums") or []],
        "virtual": {
            "all": {"id": "all", "name": "全部成片", "count": len(pool)},
            "unfiled": {"id": "unfiled", "name": "未分辑", "count": len(unfiled)},
        },
        "groups": {
            "persons": _group_counts(pool, "person"),
            "person_min": PERSON_MAIN_MIN,
        },
    }


@router.post("/api/albums")
def create_album(req: Dict[str, Any]):
    name = str((req or {}).get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="专辑名不能为空")
    if name in RESERVED_ALBUM_NAMES:
        raise HTTPException(status_code=400, detail=f"「{FAVORITES_NAME}」是系统分类，不能再建同名专辑")
    now = int(time.time())
    album = {
        "id": str(uuid.uuid4()),
        "name": name[:80],
        "cover_card_id": "",
        "created_at": now,
        "updated_at": now,
        "card_ids": [],
    }
    with _LOCK:
        store = _load_store()
        store["albums"].append(album)
        _save_store(store)
    return {"album": _public_album(album)}


@router.patch("/api/albums/{album_id}")
def patch_album(album_id: str, req: Dict[str, Any]):
    if album_id in VIRTUAL_IDS:
        raise HTTPException(status_code=400, detail="虚拟专辑不能修改")
    req = req or {}
    with _LOCK:
        store = _load_store()
        album = _find_album(store, album_id)
        if album_id == FAVORITES_ID and "name" in req:
            raise HTTPException(status_code=400, detail="系统分类不能改名")
        if "name" in req:
            name = str(req.get("name") or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="专辑名不能为空")
            if name in RESERVED_ALBUM_NAMES:
                raise HTTPException(status_code=400, detail=f"「{FAVORITES_NAME}」是系统分类，不能占用这个名字")
            album["name"] = name[:80]
        if "cover_card_id" in req:
            cover = str(req.get("cover_card_id") or "").strip()
            if cover and cover not in (album.get("card_ids") or []):
                raise HTTPException(status_code=400, detail="封面必须是本专辑内的卡片")
            album["cover_card_id"] = cover
        album["updated_at"] = int(time.time())
        _save_store(store)
        out = _public_album(album)
    return {"album": out}


@router.delete("/api/albums/{album_id}")
def delete_album(album_id: str):
    if album_id in VIRTUAL_IDS or album_id == FAVORITES_ID:
        raise HTTPException(status_code=400, detail="系统分类不能删除")
    with _LOCK:
        store = _load_store()
        before = len(store.get("albums") or [])
        store["albums"] = [a for a in store.get("albums") or [] if a.get("id") != album_id]
        if len(store["albums"]) == before:
            raise HTTPException(status_code=404, detail="专辑不存在")
        _save_store(store)
    return {"status": "deleted"}


@router.put("/api/albums/{album_id}/cards")
def put_album_cards(album_id: str, req: Dict[str, Any]):
    if album_id in VIRTUAL_IDS:
        raise HTTPException(status_code=400, detail="虚拟专辑不能改卡片集合")
    req = req or {}
    with _LOCK:
        store = _load_store()
        album = _find_album(store, album_id)
        ids = list(album.get("card_ids") or [])
        if "card_ids" in req:
            next_ids: List[str] = []
            seen = set()
            for item in req.get("card_ids") or []:
                cid = str(item or "").strip()
                if not cid or cid in seen:
                    continue
                seen.add(cid)
                next_ids.append(cid)
            ids = next_ids
        else:
            for cid in req.get("add") or []:
                cid = str(cid or "").strip()
                if cid and cid not in ids:
                    ids.append(cid)
            remove = {str(x or "").strip() for x in (req.get("remove") or []) if str(x or "").strip()}
            if remove:
                ids = [x for x in ids if x not in remove]
        album["card_ids"] = ids
        cover = str(album.get("cover_card_id") or "")
        if cover and cover not in ids:
            album["cover_card_id"] = ids[0] if ids else ""
        elif not cover and ids:
            album["cover_card_id"] = ids[0]
        album["updated_at"] = int(time.time())
        _save_store(store)
        out = _public_album(album)
    return {"album": out}


@router.get("/api/albums/pool")
def album_pool(
    album_id: str = "all",
    month: str = "all",
    person: str = "",
    scene: str = "",
    theme: str = "",
    include_unrendered: bool = False,
):
    key = str(album_id or "all").strip() or "all"
    with _LOCK:
        store = _load_store()
        if key not in VIRTUAL_IDS:
            _find_album(store, key)
        cards = _all_cards()
        items = _filter_pool(
            cards,
            album_id=key,
            store=store,
            month=str(month or "all").strip() or "all",
            person=str(person or "").strip(),
            scene=str(scene or "").strip(),
            theme=str(theme or "").strip(),
            include_unrendered=bool(include_unrendered),
        )
        facets_source = _filter_pool(
            cards,
            album_id=key,
            store=store,
            month="all",
            person="",
            scene="",
            theme="",
            include_unrendered=bool(include_unrendered),
        )
    return {
        "album_id": key,
        "items": items,
        "total": len(items),
        "facets": _facets(facets_source),
    }
