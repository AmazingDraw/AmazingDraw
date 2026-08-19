"""
card_engine_core — 正式版稳定 API。

加载优先级：
  1. card_engine_core/native/*.so 或 *.pyd
"""
from __future__ import annotations

import sys
from pathlib import Path

_RELEASE = Path(__file__).resolve().parents[1]
_NATIVE = Path(__file__).resolve().parent / "native"
_VENDOR_ENGINE = _RELEASE / "_unused_vendor_engine"

if _NATIVE.is_dir():
    p = str(_NATIVE)
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

if _VENDOR_ENGINE.is_dir():
    p = str(_VENDOR_ENGINE)
    if p not in sys.path:
        sys.path.append(p)

__version__ = "0.2.0-native"


def _compiled_modules() -> list:
    if not _NATIVE.is_dir():
        return []
    names = []
    mods = list(_NATIVE.glob("*.so")) + list(_NATIVE.glob("*.pyd"))
    for mod in sorted(mods):
        names.append(mod.name.split(".")[0])
    return names


def health() -> dict:
    compiled = _compiled_modules()
    info = {
        "version": __version__,
        "mode": "native_so" if compiled else "vendor_shim",
        "native_dir": str(_NATIVE),
        "compiled_modules": compiled,
        "compiled_count": len(compiled),
        "vendor_engine": str(_VENDOR_ENGINE),
        "vendor_present": _VENDOR_ENGINE.is_dir(),
        "assets_bin": (_RELEASE / "assets.bin").is_file()
        or (_RELEASE / "dist" / "assets.bin").is_file(),
    }
    try:
        import card_config  # type: ignore

        info["card_config_file"] = getattr(card_config, "__file__", "")
        info["tmp_dir"] = str(getattr(card_config, "TMP_DIR", ""))
        info["cards_dir"] = str(getattr(card_config, "CARDS_DIR", ""))
        info["using_so"] = str(info["card_config_file"]).endswith((".so", ".pyd"))
    except Exception as e:
        info["card_config_error"] = str(e)
    return info


def initialize_new_card(args):
    from card_core import initialize_new_card as _impl  # type: ignore

    return _impl(args)


def render_prompt(card):
    import card_rendering as R  # type: ignore

    for name in ("cmd_render", "cmd_render_silent", "render_card", "build_prompt", "render_prompt"):
        fn = getattr(R, name, None)
        if callable(fn):
            return fn(card)
    raise NotImplementedError("card_rendering 无可用 render 入口")


def validate_card(card):
    import card_validation as V  # type: ignore

    for name in ("check_card", "run_preflight_check", "validate_card", "run_validation"):
        fn = getattr(V, name, None)
        if callable(fn):
            return fn(card)
    raise NotImplementedError("card_validation 无可用 validate 入口")


def autofix_card(card):
    import card_autofix as A  # type: ignore

    for name in (
        "safe_autofix_card_text_fields",
        "autofix_card",
        "apply_autofix",
        "run_autofix",
    ):
        fn = getattr(A, name, None)
        if callable(fn):
            return fn(card)
    raise NotImplementedError("card_autofix 无可用 autofix 入口")


__all__ = [
    "health",
    "initialize_new_card",
    "render_prompt",
    "validate_card",
    "autofix_card",
    "__version__",
]
