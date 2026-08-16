"""
Optional addon: lets the server owner upload community-made AssetBundles
(registered as real networked prefabs by TavernLib) and offer them to
connecting clients. Delete this addons/custom_models/ folder (both
server.py and client.py) and the feature disappears cleanly from both
apps -- core's auth_service/header code never hardcodes anything about
it; this file registers itself into both registries instead.
"""
import os
import json
import struct
import threading
import hashlib
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED, GREEN, RED, CYAN,
    _btn, _mk_tree,
)
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window, _set_window_icon
from tavern_shared.paths import _tavern_data_dir
from server.core.auth_service import register_auth_handler
from server.core.header_registry import register_header_button

CUSTOM_ASSETS_DIR      = os.path.join(_tavern_data_dir(), "CustomAssets")


CUSTOM_ASSETS_MANIFEST = os.path.join(CUSTOM_ASSETS_DIR, "manifest.json")


CUSTOM_ASSET_NAME_MAX_LEN = 48


_assets_lock = threading.RLock()


def _load_asset_manifest():
    with _assets_lock:
        try:
            with open(CUSTOM_ASSETS_MANIFEST, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("assets", {})   # name -> {filename, sha256, size}
        return data


def _save_asset_manifest(data):
    with _assets_lock:
        try:
            with open(CUSTOM_ASSETS_MANIFEST, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


def _clean_asset_name(display_name):
    """Same idea as the ticket text cleaner — squashes a display name down
    to something safe to use as both a dict key and a filename on disk."""
    name = "".join(c for c in str(display_name).strip().lower()
                    if c.isalnum() or c in "_-")
    return name[:CUSTOM_ASSET_NAME_MAX_LEN]


def _sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def register_custom_asset_bundle(display_name, source_path, base_hash=0, log_fn=lambda *a: None):
    """Called from the Custom Models window after the admin picks a .bundle
    file. Copies it into CustomAssets/, records its hash in the manifest,
    and makes it immediately visible to the manifest handshake below —
    no server restart needed for a client to pick up a newly added model.

    base_hash is optional (0 means none) — the hash of an existing prefab
    (e.g. from 'spawn find' in-game) whose behaviour this custom model
    should inherit: collision, whether it can be picked up, physics, etc.
    Only its mesh/material gets swapped for the uploaded bundle's own;
    everything else about how it behaves comes from that base prefab."""
    name = _clean_asset_name(display_name)
    if not name:
        return {"status": "error", "message": "Invalid name."}
    if not os.path.isfile(source_path):
        return {"status": "error", "message": "Source file not found."}
    try:
        base_hash = int(base_hash)
    except (TypeError, ValueError):
        return {"status": "error", "message": "Base prefab hash must be a number."}

    filename  = f"{name}.bundle"
    dest_path = os.path.join(CUSTOM_ASSETS_DIR, filename)
    shutil.copyfile(source_path, dest_path)
    sha256 = _sha256_of_file(dest_path)

    # Written directly here (not just handed to clients over the manifest)
    # because the server's own game process reads straight out of this same
    # CustomAssets/ folder — it never goes through the client's download/
    # sync path, so this is the only place that copy of the sidecar exists.
    sidecar_path = os.path.join(CUSTOM_ASSETS_DIR, f"{name}.json")
    try:
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump({"base_hash": base_hash}, f)
    except Exception:
        pass

    with _assets_lock:
        manifest = _load_asset_manifest()
        manifest["assets"][name] = {
            "filename":  filename,
            "sha256":    sha256,
            "size":      os.path.getsize(dest_path),
            "base_hash": base_hash,
        }
        _save_asset_manifest(manifest)

    base_note = f", based on prefab {base_hash}" if base_hash else ""
    log_fn(f"Registered custom asset bundle '{name}' ({os.path.getsize(dest_path)} bytes{base_note})", "ok")
    return {"status": "ok", "name": name}


def remove_custom_asset_bundle(name, log_fn=lambda *a: None):
    """Removes both the manifest entry and the file on disk. A client that
    already downloaded it keeps its local copy — TavernLib doesn't currently
    have an eviction path — but it stops being offered to new joiners."""
    with _assets_lock:
        manifest = _load_asset_manifest()
        entry = manifest["assets"].pop(name, None)
        _save_asset_manifest(manifest)
    if entry:
        try:
            os.remove(os.path.join(CUSTOM_ASSETS_DIR, entry["filename"]))
        except Exception:
            pass
        try:
            os.remove(os.path.join(CUSTOM_ASSETS_DIR, f"{name}.json"))
        except Exception:
            pass
        log_fn(f"Removed custom asset bundle '{name}'", "warn")
    return entry is not None


def _send_asset_bytes(conn, name):
    """Writes an 8-byte big-endian length prefix followed by the bundle's
    raw bytes onto an already-connected auth-port socket, or a single
    zero-length prefix (and nothing else) if the name isn't registered or
    the file can't be read. Shares the connection with everything else
    _handle_auth does — this is just the one branch that answers in binary
    instead of JSON."""
    manifest = _load_asset_manifest()
    entry = manifest["assets"].get(name)
    if not entry:
        conn.sendall(struct.pack(">Q", 0))
        return
    full_path = os.path.join(CUSTOM_ASSETS_DIR, entry["filename"])
    try:
        with open(full_path, "rb") as f:
            data = f.read()
    except Exception:
        conn.sendall(struct.pack(">Q", 0))
        return
    # A multi-MB bundle over a slow link can easily outrun the 5s timeout
    # _handle_auth sets for the normal (small, JSON) request/response —
    # widen it just for the actual send, same idea as _download_with_progress's
    # own generous wall-clock budget on the client side.
    conn.settimeout(60)
    conn.sendall(struct.pack(">Q", len(data)))
    conn.sendall(data)


class CustomModelsWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        _start_hidden(self)
        self.title("Custom Models")
        self.configure(bg=BG)
        self.geometry("620x480")
        self.resizable(True, True)
        _set_window_icon(self)
        # Guarded rather than called unconditionally -- ttk.Style() is a
        # single global object shared across the whole app, and
        # unconditionally re-invoking theme_use() every time any window
        # opens (even redundantly re-setting the SAME theme) can reset
        # custom style configurations already applied elsewhere (e.g. a
        # combobox styled by an already-open window), which is almost
        # certainly why collapsed comboboxes intermittently reverted to
        # plain white once more than one window was involved.
        if ttk.Style().theme_use() != "clam":
            ttk.Style().theme_use("clam")
        self._build()
        self._refresh()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        _finish_dark_window(self)
        self.update_idletasks()
        fit_w = max(620, self.winfo_reqwidth())
        fit_h = max(480, self.winfo_reqheight())
        self.geometry(f"{fit_w}x{fit_h}")
        self.minsize(fit_w, fit_h)

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="🗿  Custom Models", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        tk.Label(self,
            text="Upload AssetBundles built in Unity so players can spawn them "
                 "in-game through the console (once TavernLib is installed). "
                 "Bundles should contain visual assets only — meshes and "
                 "materials, no scripts — TavernLib wires up the networking "
                 "side itself when it loads the bundle.",
            bg=BG, fg=MUTED, font=("Segoe UI",9), wraplength=560, justify="left"
        ).pack(anchor="w", padx=20, pady=(10,6))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(0,6))
        self.tree = _mk_tree(body, ("name","size","base_hash","sha256"),
                            [160,80,90,240], height=12)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        br = tk.Frame(self, bg=BG)
        br.pack(fill="x", padx=16, pady=(0,12))
        _btn(br, "➕ Add Model", self._add_model, "primary",
             font=("Segoe UI",9), pady=6, padx=12).pack(side="left")
        self._remove_btn = _btn(br, "🗑 Remove", self._remove_model, "danger",
                                font=("Segoe UI",9), pady=6, padx=12)
        self._remove_btn.pack(side="left", padx=(6,0))
        self._remove_btn.config(state="disabled")
        _btn(br, "⟳ Refresh", self._refresh, font=("Segoe UI",9),
             pady=6, padx=12).pack(side="right")

        self._status = tk.StringVar(value="")
        tk.Label(self, textvariable=self._status, bg=BG, fg=CYAN,
                 font=("Segoe UI",9), wraplength=580, justify="left"
        ).pack(anchor="w", padx=20, pady=(0,10))

    def _refresh(self):
        for r in self.tree.get_children(): self.tree.delete(r)
        manifest = _load_asset_manifest()
        for name, info in sorted(manifest["assets"].items()):
            size_kb = f"{info['size'] / 1024:.1f} KB"
            base_hash = info.get("base_hash", 0)
            base_display = str(base_hash) if base_hash else "—"
            self.tree.insert("", "end", iid=name,
                             values=(name, size_kb, base_display, info["sha256"][:16] + "…"))
        self._remove_btn.config(state="disabled")

    def _on_select(self, _=None):
        self._remove_btn.config(state="normal" if self.tree.selection() else "disabled")

    def _add_model(self):
        path = filedialog.askopenfilename(
            title="Select AssetBundle",
            filetypes=[("AssetBundle","*.bundle"),("All","*.*")], parent=self)
        if not path:
            return

        default_name = os.path.splitext(os.path.basename(path))[0]
        prompt = tk.Toplevel(self)
        _start_hidden(prompt)
        prompt.title("Add Custom Model"); prompt.configure(bg=BG)
        prompt.resizable(False, False); prompt.geometry("380x330")
        tk.Label(prompt, text="Name for this model",
                 bg=BG, fg=PARCH, font=("Georgia",11,"bold")).pack(pady=(16,4))
        tk.Label(prompt,
                 text="Used as its console spawn name — letters, numbers,\n"
                      "hyphens, and underscores only.",
                 bg=BG, fg=MUTED, font=("Segoe UI",9)).pack()
        var = tk.StringVar(value=default_name)
        ef = tk.Frame(prompt, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        ef.pack(padx=30, pady=10, fill="x")
        tk.Entry(ef, textvariable=var, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",11),
                 bd=6, justify="center").pack(fill="x")

        tk.Label(prompt, text="Base prefab hash (optional)",
                 bg=BG, fg=PARCH, font=("Georgia",11,"bold")).pack(pady=(10,4))
        tk.Label(prompt,
                 text="Makes this model inherit an existing prefab's behaviour\n"
                      "— collision, whether it can be picked up, etc. — and only\n"
                      "swaps in your mesh. Find one with 'spawn find <name>' in\n"
                      "the console. Leave blank for a bare, un-pickupable block.",
                 bg=BG, fg=MUTED, font=("Segoe UI",9), justify="left").pack(padx=20)
        base_var = tk.StringVar(value="")
        bf = tk.Frame(prompt, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        bf.pack(padx=30, pady=10, fill="x")
        tk.Entry(bf, textvariable=base_var, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",11),
                 bd=6, justify="center").pack(fill="x")

        def confirm():
            name = _clean_asset_name(var.get())
            if not name:
                messagebox.showerror("Invalid name",
                    "Use letters, numbers, hyphens, or underscores.", parent=prompt)
                return
            base_text = base_var.get().strip()
            if base_text:
                try:
                    base_hash = int(base_text)
                except ValueError:
                    messagebox.showerror("Invalid base hash",
                        "Base prefab hash must be a whole number (from 'spawn find' "
                        "in-game), or left blank.", parent=prompt)
                    return
            else:
                base_hash = 0
            prompt.destroy()
            resp = register_custom_asset_bundle(name, path, base_hash=base_hash, log_fn=lambda *a: None)
            if resp.get("status") == "ok":
                self._status.set(f"Added '{resp['name']}'.")
                self._refresh()
            else:
                messagebox.showerror("Failed",
                    resp.get("message","Could not register bundle."), parent=self)

        _btn(prompt, "Add", confirm, "primary",
             font=("Georgia",10,"bold"), pady=8).pack(fill="x", padx=30, pady=(10,14))
        _finish_dark_window(prompt)

    def _remove_model(self):
        sel = self.tree.selection()
        if not sel:
            return
        name = sel[0]
        if not messagebox.askyesno("Remove Model",
                f"Remove '{name}'? Players who already downloaded it keep "
                "their local copy, but new joiners won't be offered it.",
                parent=self):
            return
        remove_custom_asset_bundle(name, log_fn=lambda *a: None)
        self._status.set(f"Removed '{name}'.")
        self._refresh()


# ── auth-port dispatch handlers ──────────────────────────────────────────
# The exact two branches _handle_auth used to hardcode, now registered
# instead -- core's auth_service.py has no idea this addon exists.

def _handle_manifest_request(conn, req, ip, log_fn):
    manifest = _load_asset_manifest()
    resp = {
        "status": "ok",
        "assets": [
            {
                "name": name,
                "sha256": info["sha256"],
                "size": info["size"],
                "base_hash": info.get("base_hash", 0),
            }
            for name, info in manifest["assets"].items()
        ],
    }
    conn.sendall(json.dumps(resp).encode())


def _handle_download_request(conn, req, ip, log_fn):
    name = str(req.get("asset_download_request", "")).strip()
    _send_asset_bytes(conn, name)


register_auth_handler(lambda req: req.get("asset_manifest_request"), _handle_manifest_request)
register_auth_handler(lambda req: req.get("asset_download_request"), _handle_download_request)

# ── header button ─────────────────────────────────────────────────────────
# ServerLauncher itself has no _open_custom_models method anymore -- this
# addon supplies both the button registration AND the method it points
# at, attached directly onto the ServerLauncher class.

def _open_custom_models(self):
    if getattr(self, "_models_win", None) and self._models_win.winfo_exists():
        self._models_win.lift(); return
    self._models_win = CustomModelsWindow(self)


def _install_on_server_launcher():
    # Deferred import to avoid a circular dependency (launcher_window.py
    # doesn't need to know about this addon at all; this addon reaches
    # into it, not the other way around).
    from server.core.launcher_window import ServerLauncher
    ServerLauncher._open_custom_models = _open_custom_models
    ServerLauncher._models_win = None


_install_on_server_launcher()
register_header_button("custom_models", "🗿 Models", "_open_custom_models")
