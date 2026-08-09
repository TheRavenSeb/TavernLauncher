"""
Reads addons/<name>/author.json -- the small, mandatory metadata file
every addon ships: display name, author, version, and optionally which
Mods/Plugins DLLs it needs installed alongside it. Anyone can submit an
addon, so a missing or malformed file must never crash either app --
it just falls back to sensible defaults, which also doubles as a
visible signal for whoever's reviewing a merge request.
"""
import os
import json


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    return [text] if text else []


def load_addon_manifest(addons_dir, addon_name):
    """Returns a dict with "name", "author", "version" (always present,
    even on missing/malformed input), plus "required_mods" and
    "required_plugins" -- each a list of {"title", "filename"} dicts,
    empty if the addon doesn't declare any."""
    fallback = {
        "name": addon_name, "author": "Unknown", "version": "?",
        "required_mods": [], "required_plugins": [],
    }
    path = os.path.join(addons_dir, addon_name, "author.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return fallback

        def _pairs(title_key, filename_key):
            titles = _as_list(data.get(title_key))
            filenames = _as_list(data.get(filename_key))
            return [{"title": t, "filename": filenames[i] if i < len(filenames) else t}
                    for i, t in enumerate(titles)]

        return {
            "name": str(data.get("name") or addon_name).strip() or addon_name,
            "author": str(data.get("author") or "Unknown").strip() or "Unknown",
            "version": str(data.get("version") or "?").strip() or "?",
            "required_mods": _pairs("required_mods_title", "required_mods_filename"),
            "required_plugins": _pairs("required_plugins_title", "required_plugins_filename"),
        }
    except Exception:
        return fallback


def is_dependency_installed(game_dir, filename_pattern, subfolder):
    """Loose match: case-insensitive "starts with" against whatever's in
    Mods/ or Plugins/, so "TavernModels" still matches a future
    "TavernModelsv1.2.dll" without needing an exact version match.
    Returns False (not an error) if game_dir isn't set or doesn't exist --
    callers show that as "can't check yet", same as "not found"."""
    if not game_dir:
        return False
    folder = os.path.join(game_dir, subfolder)
    if not os.path.isdir(folder):
        return False
    pattern = filename_pattern.strip().lower()
    if pattern.endswith(".dll"):
        pattern = pattern[:-4]
    try:
        for fn in os.listdir(folder):
            if fn.lower().endswith(".dll") and fn.lower().startswith(pattern):
                return True
    except Exception:
        pass
    return False
