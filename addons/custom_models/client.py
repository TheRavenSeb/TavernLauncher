"""
Optional addon: lets a server offer community-uploaded custom models
(AssetBundles registered as real networked prefabs by TavernLib), synced
down to this client before each launch. Delete this addons/custom_models/
folder (both server.py and client.py) and the feature disappears from
both apps cleanly -- core never hardcodes a call to sync_custom_assets;
it registers itself as a post-auth hook instead.
"""
import os
import json
import struct
import socket
import hashlib
import shutil
import glob

from client.core.auth import AUTH_PORT
from client.core.config import _safe_part
from tavern_shared.paths import _tavern_data_dir
from client.core.launch_hooks import register_post_auth_hook

CUSTOM_ASSETS_DIR = os.path.join(_tavern_data_dir(), "CustomAssets")


CUSTOM_ASSETS_CACHE_ROOT = os.path.join(_tavern_data_dir(), "CustomAssetsCache")


def _custom_assets_cache_dir(host):
    return os.path.join(CUSTOM_ASSETS_CACHE_ROOT, _safe_part(host))


def asset_manifest_request(host, timeout=10):
    """Sends one asset_manifest_request to a server's auth port and returns
    the parsed JSON response. Same shape as ticket_request/ping_server —
    raises on a connection failure, callers decide how to handle that."""
    s = socket.socket()
    s.settimeout(timeout)
    s.connect((host, AUTH_PORT))
    s.sendall(json.dumps({"asset_manifest_request": True}).encode())
    raw = s.recv(65536)
    s.close()
    return json.loads(raw.decode())


def _recv_exact(sock, n):
    """recv() has no guarantee of returning all n bytes in one call — this
    loops until exactly n bytes have arrived (or the connection dies)."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(1 << 16, n - len(buf)))
        if not chunk:
            raise RuntimeError("Connection closed before expected data was fully received")
        buf.extend(chunk)
    return bytes(buf)


def download_asset_bundle(host, name, timeout=60):
    """Requests one custom asset bundle's raw bytes over the same auth-port
    (1762) connection used for everything else — deliberately not a second
    port, since the game already needs a long list of ports forwarded.
    The server replies with an 8-byte big-endian length prefix followed by
    that many bytes; a prefix of 0 means it doesn't have (or couldn't read)
    an asset by that name. Returns the raw bytes; raises on any failure."""
    s = socket.socket()
    s.settimeout(timeout)
    s.connect((host, AUTH_PORT))
    s.sendall(json.dumps({"asset_download_request": name}).encode())

    total = struct.unpack(">Q", _recv_exact(s, 8))[0]
    if total == 0:
        s.close()
        raise RuntimeError(f"Server has no asset named '{name}'")

    data = _recv_exact(s, total)
    s.close()
    return data


def _sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sync_custom_assets(host, log_fn=lambda *a: None):
    """Called once per successful auth, before launching the game. Downloads
    any custom asset bundle that's missing from THIS server's persistent
    cache or whose sha256 no longer matches the server's copy, then fully
    replaces the flat CUSTOM_ASSETS_DIR (the one TavernLib actually reads)
    with exactly this server's current set, copied from that cache.
    Deliberately blocking — TavernLib registers whatever bundles are on
    disk at launch, so the game must not start until this client's set
    matches the server's, or a spawn message referencing a prefab hash
    this client never registered would just fail silently.
    Never raises — a server with no custom assets, or one that's offline
    for this specific handshake, just means nothing gets synced this
    launch (and the flat folder is left as whatever it last was, rather
    than being wiped on a failed handshake)."""
    try:
        resp = asset_manifest_request(host)
    except Exception as e:
        log_fn(f"Could not fetch custom asset manifest: {e}", "warn")
        return

    if resp.get("status") != "ok":
        return

    assets = resp.get("assets", [])
    cache_dir = _custom_assets_cache_dir(host)
    os.makedirs(cache_dir, exist_ok=True)

    for asset in assets:
        name, sha256 = asset["name"], asset["sha256"]
        base_hash = asset.get("base_hash", 0)
        cached_bundle  = os.path.join(cache_dir, f"{name}.bundle")
        cached_sidecar = os.path.join(cache_dir, f"{name}.json")

        # base_hash can change without the mesh changing, so rewrite it
        # every sync regardless of the bundle's own sha256 check below.
        try:
            with open(cached_sidecar, "w", encoding="utf-8") as f:
                json.dump({"base_hash": base_hash}, f)
        except Exception as e:
            log_fn(f"Failed to write metadata for '{name}': {e}", "warn")

        if os.path.isfile(cached_bundle) and _sha256_of_file(cached_bundle) == sha256:
            continue  # this server's cache already has the current version

        log_fn(f"Downloading custom asset '{name}'…", "dim")
        try:
            data = download_asset_bundle(host, name)
            with open(cached_bundle, "wb") as f:
                f.write(data)
            if _sha256_of_file(cached_bundle) != sha256:
                log_fn(f"Custom asset '{name}' failed checksum after download", "err")
                os.remove(cached_bundle)
        except Exception as e:
            log_fn(f"Failed to download custom asset '{name}': {e}", "err")

    # TavernLib reads one flat folder with no idea which server it's
    # talking to, so it gets fully repopulated from this server's cache
    # every time instead of accumulating stale leftovers.
    try:
        for stale in (glob.glob(os.path.join(CUSTOM_ASSETS_DIR, "*.bundle")) +
                      glob.glob(os.path.join(CUSTOM_ASSETS_DIR, "*.json"))):
            os.remove(stale)
    except Exception as e:
        log_fn(f"Failed to clear previous server's custom assets: {e}", "warn")

    staged = 0
    for asset in assets:
        name = asset["name"]
        cached_bundle  = os.path.join(cache_dir, f"{name}.bundle")
        cached_sidecar = os.path.join(cache_dir, f"{name}.json")
        try:
            if os.path.isfile(cached_bundle):
                shutil.copy2(cached_bundle, os.path.join(CUSTOM_ASSETS_DIR, f"{name}.bundle"))
                staged += 1
            if os.path.isfile(cached_sidecar):
                shutil.copy2(cached_sidecar, os.path.join(CUSTOM_ASSETS_DIR, f"{name}.json"))
        except Exception as e:
            log_fn(f"Failed to stage custom asset '{name}': {e}", "err")

    if staged:
        log_fn(f"{staged} custom asset(s) ready for this server.", "ok")


# This is the entire connection point to core: register this addon's
# sync function to run right after every successful auth, before launch.
# Nothing in ClientLauncher._do_launch needs to know this addon exists.
register_post_auth_hook(sync_custom_assets)
