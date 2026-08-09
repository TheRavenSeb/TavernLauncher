"""
Client-side config/token persistence -- saved settings (username, last
server, toggles) and the per-server-per-username token files that prove
identity to a server's auth port.
"""
import os
import sys
import json
import glob
import shutil
import secrets
import hashlib

from tavern_shared.paths import _app_dir, _tavern_data_dir

def _migrate_legacy_file(old_path, new_path):
    """One-time move from before file storage was unified into
    _tavern_data_dir(). Safe to call every startup — a no-op once the file
    has already been moved, or if it never existed at the old location."""
    try:
        if os.path.isfile(old_path) and not os.path.isfile(new_path):
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            shutil.move(old_path, new_path)
    except Exception:
        pass


def _migrate_legacy_tokens():
    """One-time bulk move of every pre-existing token file (old single-
    file-per-username scheme and the newer per-server-pair scheme alike)
    from next to the exe into the shared tokens/ folder."""
    try:
        old_dir = _app_dir()
        new_dir = os.path.join(_tavern_data_dir(), "tokens")
        for old_path in glob.glob(os.path.join(old_dir, ".token_*.json")):
            new_path = os.path.join(new_dir, os.path.basename(old_path))
            _migrate_legacy_file(old_path, new_path)
    except Exception:
        pass


def _safe_part(s):
    return "".join(c for c in str(s).lower() if c.isalnum() or c in "-_") or "x"


def _legacy_token_file(username):
    """Old scheme: one token file per username, shared across every server."""
    return os.path.join(_tavern_data_dir(), "tokens", f".token_{_safe_part(username)}.json")


def _token_file(host, username):
    """New scheme: one token file per server+username pair, so the same
    username can hold a different, independent token on each server."""
    return os.path.join(_tavern_data_dir(), "tokens",
        f".token_{_safe_part(host)}__{_safe_part(username)}.json")


CONFIG_FILE = os.path.join(_tavern_data_dir(), "tavern_launcher.json")
_migrate_legacy_file(os.path.join(os.path.expanduser("~"), ".tavern_launcher.json"), CONFIG_FILE)
_migrate_legacy_tokens()

def _any_token_files_exist():
    """True if at least one token file (old or new naming scheme) already
    exists, regardless of which server/username it's for."""
    try:
        return bool(glob.glob(os.path.join(_tavern_data_dir(), "tokens", ".token_*.json")))
    except Exception:
        return False


def _get_or_create_token(host, username):
    """Returns (token, is_new). is_new is True only the first time this
    server+username pair gets a token file created on this machine."""
    path = _token_file(host, username)
    try:
        d = json.load(open(path))
        if d.get("username","").lower() == username.lower() and d.get("token"):
            return d["token"], False
    except: pass

    # One-time migration: if this username already had a token under the old
    # shared-across-all-servers scheme, reuse it so existing accounts on
    # servers the player already joined don't suddenly stop matching.
    token = None
    try:
        d = json.load(open(_legacy_token_file(username)))
        if d.get("username","").lower() == username.lower() and d.get("token"):
            token = d["token"]
    except: pass

    is_new = token is None
    if token is None:
        token = secrets.token_urlsafe(18)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump({"username": username, "host": host, "token": token}, open(path,"w"))
    except: pass
    return token, is_new


def load_cfg():
    try: return json.load(open(CONFIG_FILE))
    except: return {}


def save_cfg(d):
    try: json.dump(d, open(CONFIG_FILE,"w"), indent=2)
    except: pass


PLATFORM_DISPLAY_TO_BACKEND = {"SteamVR": "openvr", "Quest": "oculus", "Fly": "fly"}


PLATFORM_LEGACY_TO_DISPLAY  = {"OpenVR": "SteamVR", "Oculus": "Quest"}


USERNAME_MAX_LEN = 16


USERNAME_EXTRA_CHARS = " -_"


def _is_valid_username(username):
    """ASCII letters/digits plus space, hyphen, underscore — keeps usernames
    safe to embed in file names (token cache) and launch args without escaping."""
    return all((c.isalnum() and c.isascii()) or c in USERNAME_EXTRA_CHARS
               for c in username)


GAME_LOG_PATH = os.path.join(
    os.path.expanduser("~"), "AppData", "Roaming",
    "A Township Tale", "Client", "logs", "unity-log.csv"
)


COMMUNITY_API = "http://themoddingtavern.com:1763/servers"


DISCORD_URL   = "https://discord.gg/jNQUUDAYSj"


TICKET_RECENT_HOSTS_MAX = 6


def _remember_ticket_state(host, username):
    """Called whenever the Tickets window actually looks at a host's
    tickets -- both so reopening the window later auto-loads exactly
    what you were last looking at, and so the host field's dropdown has
    something to suggest."""
    cfg = load_cfg()
    recent = [h for h in cfg.get("ticket_recent_hosts", []) if h != host]
    recent.insert(0, host)
    cfg["ticket_recent_hosts"] = recent[:TICKET_RECENT_HOSTS_MAX]
    cfg["last_ticket_host"] = host
    cfg["last_ticket_username"] = username
    save_cfg(cfg)


def _get_last_ticket_state():
    """Returns (last_host, last_username, recent_hosts)."""
    cfg = load_cfg()
    return (cfg.get("last_ticket_host", ""), cfg.get("last_ticket_username", ""),
            cfg.get("ticket_recent_hosts", []))


TICKET_LAST_SEEN_FILE = os.path.join(_tavern_data_dir(), "ticket_last_seen.json")


def _load_ticket_last_seen():
    try:
        with open(TICKET_LAST_SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_ticket_last_seen(data):
    try:
        os.makedirs(os.path.dirname(TICKET_LAST_SEEN_FILE), exist_ok=True)
        with open(TICKET_LAST_SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def _mark_tickets_seen(host, tickets):
    """Called whenever TicketsWindow actually fetches+shows a host's
    tickets -- records "I've now seen this ticket's current state",
    which is what clears the flashing indicator for it afterward."""
    data = _load_ticket_last_seen()
    for t in tickets:
        data[f"{host}||{t.get('ticket_id')}"] = t.get("updated_at", 0)
    _save_ticket_last_seen(data)


def _known_ticket_hosts():
    """Every server host the user has ever opened TicketsWindow against --
    used to know which servers are worth periodically polling for new
    owner replies without needing one single "current server" concept."""
    hosts = set()
    for key in _load_ticket_last_seen():
        host = key.split("||", 1)[0]
        if host:
            hosts.add(host)
    return hosts


def _has_unseen_owner_reply(host, tickets):
    """True if any of this host's tickets have a newer updated_at than
    what was last seen AND the most recent comment is from the owner --
    a player's own new message obviously shouldn't flash "you have a
    reply", only an actual response from the other side should."""
    last_seen = _load_ticket_last_seen()
    for t in tickets:
        comments = t.get("comments", [])
        if not comments or comments[-1].get("from") != "owner":
            continue
        key = f"{host}||{t.get('ticket_id')}"
        if t.get("updated_at", 0) > last_seen.get(key, 0):
            return True
    return False

