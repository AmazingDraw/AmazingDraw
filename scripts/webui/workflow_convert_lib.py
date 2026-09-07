#!/usr/bin/env python3
"""Standalone ComfyUI UI-JSON → API-JSON conversion (no FastAPI / web_server deps).

Shared by AmazingDraw WebUI (`api_queue.convert_workflow_api`) and comfyui-ops CLI
(`convert_workflow.py`). Keep behavior identical to the former inlined helpers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# --- UI → API workflow conversion (aligned with Comfy graphToPrompt practices) ---

_VIRTUAL_NODE_TYPES = frozenset({
    "Note",
    "MarkdownNote",
    "Reroute",
    "PrimitiveNode",
    "Primitive String",
    "Primitive Integer",
    "Primitive Float",
    "Primitive Boolean",
})

_PRIMITIVE_NODE_TYPES = frozenset({
    "PrimitiveNode",
    "Primitive String",
    "Primitive Integer",
    "Primitive Float",
    "Primitive Boolean",
})

_CONTROL_AFTER_GENERATE_VALUES = frozenset({
    "fixed",
    "increment",
    "decrement",
    "randomize",
})

# LiteGraph modes: 0=ALWAYS, 2=BYPASS, 4=NEVER (muted)
_SKIP_NODE_MODES = frozenset({2, 4})

_WIDGET_SCALAR_TYPES = frozenset({
    "INT",
    "FLOAT",
    "STRING",
    "BOOLEAN",
    "BOOL",
    "COMBO",
    "IMAGEUPLOAD",
})

_POWER_LORA_CLASS_TYPES = frozenset({
    "Power Lora Loader (rgthree)",
})


def _is_api_workflow(data: Any) -> bool:
    """True if payload already looks like Comfy API prompt JSON (id → {class_type, inputs})."""
    if not isinstance(data, dict) or not data:
        return False
    if isinstance(data.get("nodes"), list):
        return False
    sample = []
    for key, val in data.items():
        if key.startswith("_"):
            continue
        if not isinstance(val, dict):
            return False
        sample.append(val)
        if len(sample) >= 8:
            break
    if not sample:
        return False
    return all("class_type" in node and "inputs" in node for node in sample)


def _input_type_and_opts(def_val: Any) -> Tuple[Any, Dict[str, Any]]:
    if not isinstance(def_val, list) or not def_val:
        return None, {}
    type_name = def_val[0]
    opts: Dict[str, Any] = {}
    if len(def_val) > 1 and isinstance(def_val[1], dict):
        opts = def_val[1]
    return type_name, opts


def _is_widget_input(def_val: Any) -> bool:
    """Heuristic: widget-backed inputs vs link-only sockets (MASK/AUDIO/custom → links)."""
    type_name, opts = _input_type_and_opts(def_val)
    if type_name is None:
        return False
    if opts.get("forceInput"):
        return False
    # COMBO: first element is a list/tuple of choices
    if isinstance(type_name, (list, tuple)):
        return True
    if not isinstance(type_name, str):
        return False
    if type_name.upper() in _WIDGET_SCALAR_TYPES:
        return True
    # Everything else (MODEL, IMAGE, MASK, AUDIO, LATENT, custom, …) is link-typed
    return False


def _has_control_after_generate(def_val: Any) -> bool:
    _, opts = _input_type_and_opts(def_val)
    return bool(opts.get("control_after_generate"))


def _normalize_link_entry(
    link: Any,
    synthetic_id: int,
) -> Tuple[Optional[Dict[str, Any]], int]:
    """Normalize a links[] entry to {id, origin, origin_slot, target, target_slot}.

    Supports:
      - 6+ tuple: [id, origin, origin_slot, target, target_slot, type, ...]
      - 5 tuple:  [id, origin, origin_slot, target, target_slot]
      - 4 tuple:  [origin, origin_slot, target, target_slot] (synthetic id)
      - dict with id/origin_id/origin_slot/target_id/target_slot (and aliases)
    """
    if isinstance(link, dict):
        origin = link.get("origin_id", link.get("origin"))
        origin_slot = link.get("origin_slot")
        target = link.get("target_id", link.get("target"))
        target_slot = link.get("target_slot")
        link_id = link.get("id", link.get("link_id"))
        if origin is None or origin_slot is None or target is None or target_slot is None:
            return None, synthetic_id
        if link_id is None:
            link_id = synthetic_id
            synthetic_id += 1
        return {
            "id": link_id,
            "origin": origin,
            "origin_slot": origin_slot,
            "target": target,
            "target_slot": target_slot,
        }, synthetic_id

    if not isinstance(link, (list, tuple)) or not link:
        return None, synthetic_id

    if len(link) >= 6:
        link_id, origin, origin_slot, target, target_slot = (
            link[0], link[1], link[2], link[3], link[4]
        )
    elif len(link) == 5:
        link_id, origin, origin_slot, target, target_slot = (
            link[0], link[1], link[2], link[3], link[4]
        )
    elif len(link) == 4:
        origin, origin_slot, target, target_slot = link[0], link[1], link[2], link[3]
        link_id = synthetic_id
        synthetic_id += 1
    else:
        return None, synthetic_id

    return {
        "id": link_id,
        "origin": origin,
        "origin_slot": origin_slot,
        "target": target,
        "target_slot": target_slot,
    }, synthetic_id


def _parse_links(
    ui_json: Dict[str, Any],
) -> Tuple[Dict[Any, List[Any]], Dict[str, Dict[int, Any]]]:
    """Parse workflow links.

    Returns:
      links_map: link_id → [origin_node_id(str), origin_slot(int)]
      by_target: target_node_id(str) → {target_slot(int) → link_id}
    """
    links_map: Dict[Any, List[Any]] = {}
    by_target: Dict[str, Dict[int, Any]] = {}
    synthetic_id = 1
    for link in ui_json.get("links") or []:
        normalized, synthetic_id = _normalize_link_entry(link, synthetic_id)
        if not normalized:
            continue
        link_id = normalized["id"]
        origin = normalized["origin"]
        origin_slot = normalized["origin_slot"]
        target = normalized["target"]
        target_slot = normalized["target_slot"]
        try:
            origin_slot_i = int(origin_slot)
            target_slot_i = int(target_slot)
        except (TypeError, ValueError):
            continue
        links_map[link_id] = [str(origin), origin_slot_i]
        tkey = str(target)
        by_target.setdefault(tkey, {})[target_slot_i] = link_id
    return links_map, by_target


def _link_typed_input_names(class_type: Any, object_info: Dict[str, Any]) -> List[str]:
    """Link-typed input names in required+optional declaration order (LiteGraph socket index)."""
    node_def = object_info.get(class_type) or {}
    input_def = node_def.get("input") or {}
    names: List[str] = []
    for section in ("required", "optional"):
        section_def = input_def.get(section) or {}
        if not isinstance(section_def, dict):
            continue
        for name, def_val in section_def.items():
            if not _is_widget_input(def_val):
                names.append(name)
    return names


def _resolve_input_slots(
    node: Dict[str, Any],
    by_target: Dict[str, Dict[int, Any]],
    object_info: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return input slot descriptors; synthesize from links when UI node lacks inputs[]."""
    existing = node.get("inputs")
    if existing:
        return list(existing)

    node_id = str(node.get("id"))
    slot_map = by_target.get(node_id) or {}
    if not slot_map:
        return list(existing) if isinstance(existing, list) else []

    names = _link_typed_input_names(node.get("type"), object_info)
    synthesized: List[Dict[str, Any]] = []
    for slot_idx in sorted(slot_map.keys()):
        if slot_idx < 0 or slot_idx >= len(names):
            # Out-of-range target slot (junk / widget index) — skip
            continue
        synthesized.append({
            "name": names[slot_idx],
            "link": slot_map[slot_idx],
        })
    return synthesized


def _is_rgthree_power_lora(class_type: Any) -> bool:
    if class_type in _POWER_LORA_CLASS_TYPES:
        return True
    if not isinstance(class_type, str):
        return False
    # Optional similar rgthree power loaders with the same widgets_values dict pattern
    return (
        class_type.startswith("Power ")
        and class_type.endswith("(rgthree)")
        and "Lora" in class_type
    )


def _map_rgthree_power_lora_widgets(
    inputs: Dict[str, Any],
    widgets_values: List[Any],
) -> int:
    """Map Power Lora widgets_values dicts into API keys. Returns count consumed from start."""
    lora_i = 1
    consumed = 0
    for v in widgets_values:
        if v in ("", None) or v == {}:
            consumed += 1
            continue
        if not isinstance(v, dict):
            break
        wtype = v.get("type")
        if wtype == "PowerLoraLoaderHeaderWidget" or (
            isinstance(wtype, str) and "PowerLoraLoaderHeader" in wtype
        ):
            inputs["PowerLoraLoaderHeaderWidget"] = v
            consumed += 1
            continue
        if "lora" in v or "on" in v:
            inputs[f"lora_{lora_i}"] = v
            lora_i += 1
            consumed += 1
            continue
        break
    return consumed


def _follow_reroute_and_primitive(
    links_map: Dict[Any, List[Any]],
    nodes_by_id: Dict[str, Dict[str, Any]],
    link_id: Any,
) -> Tuple[Optional[List[Any]], Optional[Any], List[str]]:
    """Resolve a link to either [node_id, slot] or a primitive scalar value."""
    warnings: List[str] = []
    if link_id not in links_map:
        return None, None, [f"missing link id {link_id}"]
    cur_id, cur_slot = links_map[link_id][0], links_map[link_id][1]
    for _ in range(32):
        node = nodes_by_id.get(str(cur_id))
        if not node:
            return [str(cur_id), cur_slot], None, warnings
        ntype = node.get("type")
        if ntype == "Reroute":
            upstream = None
            for in_slot in node.get("inputs") or []:
                up_link = in_slot.get("link")
                if up_link is not None and up_link in links_map:
                    upstream = links_map[up_link]
                    break
            if not upstream:
                warnings.append(f"Reroute node {cur_id} has no upstream link")
                return None, None, warnings
            cur_id, cur_slot = upstream[0], upstream[1]
            continue
        if ntype in _PRIMITIVE_NODE_TYPES:
            wv = node.get("widgets_values") or []
            return None, (wv[0] if wv else ""), warnings
        return [str(cur_id), cur_slot], None, warnings
    warnings.append(f"link {link_id} reroute depth exceeded")
    return [str(cur_id), cur_slot], None, warnings


def perform_workflow_conversion(
    ui_json: Dict[str, Any],
    object_info: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    """Convert ComfyUI UI-format workflow JSON to API prompt JSON.

    Returns (api_workflow, warnings). Warnings cover unknown classes, leftover
    widgets, missing required inputs, skipped virtual/muted nodes, etc.
    Does not silently claim a perfect conversion when incomplete.
    """
    warnings: List[str] = []

    if _is_api_workflow(ui_json):
        warnings.append("input already looks like API-format workflow; pass-through without conversion")
        return dict(ui_json), warnings

    if not isinstance(ui_json, dict) or not isinstance(ui_json.get("nodes"), list):
        raise ValueError("UI workflow must contain a nodes list")

    nodes_list: List[Dict[str, Any]] = ui_json.get("nodes") or []
    nodes_by_id: Dict[str, Dict[str, Any]] = {
        str(n.get("id")): n for n in nodes_list if n.get("id") is not None
    }
    links_map, by_target = _parse_links(ui_json)
    raw_links = ui_json.get("links") or []
    if raw_links and not links_map:
        warnings.append(
            "links present but none matched the expected "
            "[id, origin, origin_slot, target, target_slot, type] format "
            "(also accepts 4-tuple [origin, origin_slot, target, target_slot] and dict links)"
        )

    api_workflow: Dict[str, Any] = {}
    skipped_virtual = 0
    skipped_muted = 0

    for node in nodes_list:
        node_id = str(node.get("id"))
        class_type = node.get("type")
        if not class_type:
            warnings.append(f"node {node_id}: missing type, skipped")
            continue

        mode = node.get("mode", 0)
        if mode in _SKIP_NODE_MODES:
            skipped_muted += 1
            continue

        if class_type in _VIRTUAL_NODE_TYPES:
            skipped_virtual += 1
            continue

        inputs: Dict[str, Any] = {}

        # 1) Wire link sockets (and primitive-resolved values)
        for in_slot in _resolve_input_slots(node, by_target, object_info):
            slot_name = in_slot.get("name")
            link_id = in_slot.get("link")
            if not slot_name or link_id is None:
                continue
            resolved, prim_val, link_warns = _follow_reroute_and_primitive(
                links_map, nodes_by_id, link_id
            )
            for w in link_warns:
                warnings.append(f"node {node_id}/{slot_name}: {w}")
            if prim_val is not None and resolved is None:
                inputs[slot_name] = prim_val
            elif resolved is not None:
                origin_node = nodes_by_id.get(str(resolved[0]))
                if origin_node is not None:
                    otype = origin_node.get("type")
                    omode = origin_node.get("mode", 0)
                    if otype in _VIRTUAL_NODE_TYPES or omode in _SKIP_NODE_MODES:
                        warnings.append(
                            f"node {node_id}/{slot_name}: origin {resolved[0]} ({otype}) "
                            "is virtual/muted; link omitted"
                        )
                        continue
                inputs[slot_name] = resolved

        # 2) Widget mapping from object_info + widgets_values
        node_def = object_info.get(class_type)
        widgets_values = node.get("widgets_values")
        if widgets_values is None:
            widgets_values = []
        if not isinstance(widgets_values, list):
            if isinstance(widgets_values, dict):
                for k, v in widgets_values.items():
                    if k not in inputs:
                        inputs[k] = v
                widgets_values = []
            else:
                warnings.append(f"node {node_id} ({class_type}): widgets_values is not a list")
                widgets_values = []

        if not node_def:
            warnings.append(
                f"unknown class_type not in object_info: {class_type} (node {node_id}); "
                "install/enable this custom node on this ComfyUI, or conversion cannot map its widgets"
            )
            api_workflow[node_id] = {"inputs": inputs, "class_type": class_type}
            if widgets_values:
                warnings.append(
                    f"node {node_id} ({class_type}): {len(widgets_values)} widgets_values "
                    "unused due to missing object_info"
                )
            continue

        input_def = node_def.get("input") or {}
        required_inputs = input_def.get("required") or {}
        optional_inputs = input_def.get("optional") or {}
        all_inputs_def: Dict[str, Any] = {}
        all_inputs_def.update(required_inputs)
        all_inputs_def.update(optional_inputs)

        w_idx = 0
        for name, def_val in all_inputs_def.items():
            if not _is_widget_input(def_val):
                continue

            # Always advance widgets_values for widget-typed inputs, even if linked
            # (serialized UI keeps the value + optional control_after_generate entry).
            consumed_value = None
            if w_idx < len(widgets_values):
                consumed_value = widgets_values[w_idx]
                w_idx += 1
            if _has_control_after_generate(def_val):
                if w_idx < len(widgets_values) and (
                    widgets_values[w_idx] in _CONTROL_AFTER_GENERATE_VALUES
                    or isinstance(widgets_values[w_idx], str)
                ):
                    w_idx += 1

            if name in inputs:
                continue

            if consumed_value is not None:
                inputs[name] = consumed_value

        # 2b) rgthree Power Lora: map remaining dict widgets into lora_N / header keys
        if _is_rgthree_power_lora(class_type) and w_idx < len(widgets_values):
            consumed = _map_rgthree_power_lora_widgets(inputs, widgets_values[w_idx:])
            w_idx += consumed

        if w_idx < len(widgets_values):
            leftover = widgets_values[w_idx:]
            meaningful = [v for v in leftover if v not in ("", None)]
            if meaningful:
                warnings.append(
                    f"node {node_id} ({class_type}): {len(leftover)} leftover widgets_values "
                    f"after mapping: {meaningful[:5]!r}"
                )

        for req_name, req_def in required_inputs.items():
            if req_name in inputs:
                continue
            kind = "widget" if _is_widget_input(req_def) else "link"
            warnings.append(
                f"node {node_id} ({class_type}): missing required {kind} input '{req_name}'"
            )

        api_workflow[node_id] = {"inputs": inputs, "class_type": class_type}

    # Drop dangling links to nodes not present in API output
    present = set(api_workflow.keys())
    for nid, node_data in api_workflow.items():
        for ikey, ival in list(node_data.get("inputs", {}).items()):
            if isinstance(ival, list) and len(ival) == 2 and str(ival[0]) not in present:
                del node_data["inputs"][ikey]
                warnings.append(
                    f"node {nid}/{ikey}: removed dangling link to missing node {ival[0]}"
                )

    if skipped_virtual:
        warnings.append(
            f"skipped {skipped_virtual} virtual node(s) (Note/Reroute/Primitive/…)"
        )
    if skipped_muted:
        warnings.append(f"skipped {skipped_muted} muted/bypass node(s) (mode 2/4)")

    return api_workflow, warnings
