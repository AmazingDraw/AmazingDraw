#!/usr/bin/env python3
"""CLI: ComfyUI UI-JSON → API-JSON.

Same converter as WebUI POST /api/workflow/convert (`workflow_convert_lib`).
Does not write into ComfyUI/workflows unless -o points there.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workflow_convert_lib import perform_workflow_conversion


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert ComfyUI UI JSON to API JSON (AmazingDraw converter)."
    )
    parser.add_argument("-i", "--input", required=True, help="Path to input UI JSON file")
    parser.add_argument("-o", "--output", required=True, help="Path to output API JSON file")
    parser.add_argument(
        "--host",
        default="http://127.0.0.1:8188",
        help="ComfyUI host URL (default: http://127.0.0.1:8188)",
    )
    args = parser.parse_args()

    ui_path = Path(args.input)
    api_path = Path(args.output)

    if not ui_path.exists():
        print(f"Input file not found: {ui_path}", file=sys.stderr)
        return 1

    try:
        with open(ui_path, "r", encoding="utf-8") as f:
            wf = json.load(f)
    except Exception as e:
        print(f"JSON parsing failed: {e}", file=sys.stderr)
        return 1

    try:
        import requests

        object_info = requests.get(f"{args.host}/object_info", timeout=15).json()
    except Exception as e:
        print(f"ComfyUI unreachable at {args.host}: {e}", file=sys.stderr)
        return 1

    try:
        api, warnings = perform_workflow_conversion(wf, object_info)
    except Exception as e:
        print(f"Conversion failed: {e}", file=sys.stderr)
        return 1

    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)

    api_path.parent.mkdir(parents=True, exist_ok=True)
    with open(api_path, "w", encoding="utf-8") as f:
        json.dump(api, f, indent=2, ensure_ascii=False)

    print(f"wrote {api_path} ({len(api)} node(s), {len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
