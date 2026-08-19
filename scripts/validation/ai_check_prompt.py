#!/usr/bin/env python3
"""Dist shim: load compiled ai_check_prompt from card_engine_core/native."""
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
_native = None
for _p in [_here] + list(_here.parents):
    _cand = _p / "card_engine_core" / "native"
    if _cand.is_dir():
        _native = _cand
        break
if _native is None:
    raise SystemExit("card_engine_core/native not found")
sys.path.insert(0, str(_native))
from ai_check_prompt import main

if __name__ == "__main__":
    main()
