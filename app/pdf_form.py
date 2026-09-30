"""Customer-editable AcroForm fields named edit1, edit2, and so on."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Optional

EDIT_FIELD_RE = re.compile(r"^edit(\d+)$", re.I)
EDIT_VALUE_MAX = 500


def _deref(obj: Any) -> Any:
    if obj is None:
        return None
    get_object = getattr(obj, "get_object", None)
    if callable(get_object):
        try:
            return get_object()
        except Exception:
            return obj
    return obj


def _as_str(value: Any) -> str:
    value = _deref(value)
    if value is None:
        return ""
    text = str(value).strip()
    if text in ("None", "/None"):
        return ""
    return text


def _field_title(value: Any) -> str:
    text = _as_str(value)
    if text.startswith("/"):
        text = text[1:]
    return text


def _leaf_name(full: str) -> str:
    if not full:
        return ""
    return full.split(".")[-1].strip()


def _annot_full_name(annot: Any) -> str:
    annot = _deref(annot)
    parts: list[str] = []
    current = annot
    seen: set[int] = set()
    while current is not None and hasattr(current, "get"):
        ident = id(current)
        if ident in seen:
            break
        seen.add(ident)
        title = current.get("/T")
        if title is not None:
            parts.append(_field_title(title))
        parent = current.get("/Parent")
        current = _deref(parent) if parent is not None else None
    parts.reverse()
    return ".".join(part for part in parts if part)


def _rect_tuple(rect: Any) -> Optional[tuple[float, float, float, float]]:
    rect = _deref(rect)
    if rect is None:
        return None
    try:
        coords = [float(rect[i]) for i in range(4)]
    except Exception:
        return None
    left, bottom, right, top = coords
    if left > right:
        left, right = right, left
    if bottom > top:
        bottom, top = top, bottom
    return left, bottom, right, top


def _percent_box(rect: tuple[float, float, float, float], mediabox: Any) -> dict:
    mb_left = float(mediabox.left)
    mb_bottom = float(mediabox.bottom)
    mb_right = float(mediabox.right)
    mb_top = float(mediabox.top)
    page_width = mb_right - mb_left
    page_height = mb_top - mb_bottom
    if page_width <= 0 or page_height <= 0:
        raise ValueError("PDF page has invalid mediabox")

    left, bottom, right, top = rect
    return {
        "x": round(max((left - mb_left) / page_width * 100.0, 0.0), 2),
        "y": round(max((mb_top - top) / page_height * 100.0, 0.0), 2),
        "w": round(max((right - left) / page_width * 100.0, 0.05), 2),
        "h": round(max((top - bottom) / page_height * 100.0, 0.05), 2),
    }


def _field_value(annot: Any) -> str:
    annot = _deref(annot)
    if annot is None or not hasattr(annot, "get"):
        return ""
    value = _as_str(annot.get("/V"))
    if value:
        return value
    parent = _deref(annot.get("/Parent"))
    if parent is not None and hasattr(parent, "get"):
        return _as_str(parent.get("/V"))
    return ""


def _iter_widgets(pdf_obj: Any):
    pages = getattr(pdf_obj, "pages", None)
    if pages is None:
        return
    for page_index, page in enumerate(pages):
        annots = _deref(page.get("/Annots"))
        if not annots:
            continue
        try:
            annot_list = list(annots)
        except TypeError:
            continue
        for raw in annot_list:
            annot = _deref(raw)
            if annot is None or not hasattr(annot, "get"):
                continue
            subtype = _as_str(annot.get("/Subtype")).lstrip("/")
            if subtype and subtype.lower() != "widget":
                continue
            yield page_index, page, annot


def normalize_edit_values(edits: Optional[list]) -> dict[str, str]:
    """Keep only editN names. Keys are lowercase field names."""
    cleaned: dict[str, str] = {}
    for item in edits or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            value = item.get("value")
        else:
            name = str(getattr(item, "name", "") or "").strip()
            value = getattr(item, "value", "")
        if not EDIT_FIELD_RE.fullmatch(name):
            continue
        text = str(value or "").replace("\x00", "")
        cleaned[name.lower()] = text[:EDIT_VALUE_MAX]
    return cleaned


def list_edit_fields(pdf_path: Path) -> list[dict]:
    """Return edit1, edit2, … widgets on the PDF the signer is viewing."""
    path = Path(pdf_path) if pdf_path else None
    if path is None or not path.is_file():
        return []
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
    except Exception:
        return []

    found: list[dict] = []
    seen: set[str] = set()
    for page_index, page, annot in _iter_widgets(reader):
        leaf = _leaf_name(_annot_full_name(annot))
        match = EDIT_FIELD_RE.fullmatch(leaf)
        if not match:
            continue
        key = leaf.lower()
        if key in seen:
            continue
        rect = _rect_tuple(annot.get("/Rect"))
        if rect is None:
            continue
        try:
            box = _percent_box(rect, page.mediabox)
        except (ValueError, AttributeError):
            continue
        seen.add(key)
        found.append(
            {
                "name": leaf,
                "page": page_index + 1,
                "x": box["x"],
                "y": box["y"],
                "w": box["w"],
                "h": box["h"],
                "value": _field_value(annot)[:EDIT_VALUE_MAX],
            }
        )

    found.sort(key=lambda item: int(EDIT_FIELD_RE.fullmatch(item["name"]).group(1)))
    return found


def apply_edit_field_values(writer: Any, edits: Optional[Mapping[str, str]]) -> None:
    """Write editN values into an existing AcroForm. Other fields are left alone."""
    wanted = normalize_edit_values(
        [{"name": name, "value": value} for name, value in (edits or {}).items()]
    )
    if not wanted:
        return

    mapping: dict[str, str] = {}
    for _page_index, _page, annot in _iter_widgets(writer):
        leaf = _leaf_name(_annot_full_name(annot))
        key = leaf.lower()
        if key in wanted and leaf not in mapping:
            mapping[leaf] = wanted[key]
    if not mapping:
        return

    writer.update_page_form_field_values(None, mapping, auto_regenerate=True)
