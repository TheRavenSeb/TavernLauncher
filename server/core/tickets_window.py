"""Server-owner-side ticket viewer/responder."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading, time, json

from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED, GREEN, RED, CYAN, MONO,
    _btn, _field, _hint, _section_label, _mk_tree, _mk_scrollbar,
)
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window, _set_window_icon

from server.core.data_store import (
    _load_tickets, _save_tickets, _tickets_lock, _clean_ticket_text, TICKET_MESSAGE_MAX_LEN,
)

class TicketsWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        _start_hidden(self)
        self.title("Support Tickets")
        self.configure(bg=BG)
        self.geometry("780x600")
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
        self._tickets = []
        self._visible = []
        self._selected_ticket = None
        self._build()
        self._refresh()
        _finish_dark_window(self)
        # Same reasoning as the main launcher windows — start at exactly
        # what the fully-built layout needs, then set that as the floor,
        # so shrinking the window can never clip the Comment/Resolve row.
        self.update_idletasks()
        fit_w = max(780, self.winfo_reqwidth())
        fit_h = max(600, self.winfo_reqheight())
        self.geometry(f"{fit_w}x{fit_h}")
        self.minsize(fit_w, fit_h)

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="🎫  Support Tickets", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        sf = tk.Frame(self, bg=BG)
        sf.pack(fill="x", padx=16, pady=(10,6))
        tk.Label(sf, text="🔍", bg=BG, fg=MUTED, font=("Segoe UI",10)).pack(side="left")
        self.v_filter = tk.StringVar()
        self.v_filter.trace_add("write", lambda *_: self._populate())
        tk.Entry(sf, textvariable=self.v_filter, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6).pack(side="left", fill="x", expand=True, padx=(6,0))
        _hint_lbl = tk.Label(sf, text="filters by title or username", bg=BG, fg=MUTED,
                             font=("Segoe UI",8))
        _hint_lbl.pack(side="left", padx=(8,10))
        self.v_show_closed = tk.BooleanVar(value=False)
        tk.Checkbutton(sf, text="Show closed too", variable=self.v_show_closed,
                       command=self._populate, bg=BG, fg=MUTED, selectcolor=SURF,
                       activebackground=BG, activeforeground=AMBER,
                       font=("Segoe UI",9)).pack(side="left")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(0,10))

        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        self.tree = _mk_tree(left, ("title","username","status","updated"),
                            [220,120,70,120], height=16)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        right = tk.Frame(body, bg=SURF, highlightbackground=BORDER,
                         highlightthickness=1, width=300, height=480)
        right.pack(side="left", fill="y", padx=(10,0))
        right.pack_propagate(False)

        self.v_detail_title = tk.StringVar(value="Select a ticket")
        tk.Label(right, textvariable=self.v_detail_title, bg=SURF, fg=AMBER,
                 font=("Georgia",10,"bold"), wraplength=280, justify="left"
                 ).pack(anchor="w", padx=10, pady=(10,4))

        thread_frame = tk.Frame(right, bg=BG)
        thread_frame.pack(fill="both", expand=True, padx=10, pady=(0,6))
        self.thread_text = tk.Text(thread_frame, bg=SURF2, fg=PARCH, relief="flat",
                                   bd=0, wrap="word", state="disabled",
                                   font=("Segoe UI",9))
        tsb = _mk_scrollbar(thread_frame, self.thread_text.yview)
        tsb.pack(side="right", fill="y")
        self.thread_text.config(yscrollcommand=tsb.set)
        self.thread_text.pack(side="left", fill="both", expand=True)
        self.thread_text.tag_config("player", foreground=CYAN)
        self.thread_text.tag_config("owner", foreground=AMBER)
        self.thread_text.tag_config("meta", foreground=MUTED)

        self.v_comment = tk.StringVar()
        tk.Entry(right, textvariable=self.v_comment, bg=SURF2, fg=PARCH,
                 insertbackground=AMBER, relief="flat",
                 highlightbackground=BORDER, highlightcolor=AMBER, highlightthickness=1,
                 font=("Consolas",9), bd=6).pack(fill="x", padx=10, pady=(0,6))

        btn_row = tk.Frame(right, bg=SURF)
        btn_row.pack(fill="x", padx=10, pady=(0,10))
        _btn(btn_row, "💬 Comment", self._add_comment, font=("Segoe UI",9),
             pady=6, padx=8).pack(side="left")
        _btn(btn_row, "✔ Resolve", self._resolve_ticket, "success",
             font=("Segoe UI",9), pady=6, padx=8).pack(side="left", padx=(6,0))

        br = tk.Frame(self, bg=BG)
        br.pack(fill="x", padx=16, pady=(0,12))
        _btn(br, "⟳ Refresh", self._refresh, font=("Segoe UI",9),
             pady=6, padx=12).pack(side="left")

    def _refresh(self):
        self._tickets = _load_tickets()["tickets"]
        self._populate()

    def _populate(self):
        for r in self.tree.get_children(): self.tree.delete(r)
        query = self.v_filter.get().strip().lower()
        show_closed = self.v_show_closed.get()
        visible = []
        for t in sorted(self._tickets, key=lambda t: t["updated_at"], reverse=True):
            if not show_closed and t["status"] != "open":
                continue
            if query and query not in t["title"].lower() and query not in t["username"].lower():
                continue
            visible.append(t)
        self._visible = visible
        for t in visible:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(t["updated_at"]))
            self.tree.insert("", "end", iid=t["ticket_id"],
                             values=(t["title"], t["username"], t["status"], ts))

    def _on_select(self, _=None):
        sel = self.tree.selection()
        if not sel: return
        t = next((x for x in self._visible if x["ticket_id"] == sel[0]), None)
        if not t: return
        self._selected_ticket = t
        self.v_detail_title.set(f"{t['title']}  ({t['status']})")
        self.thread_text.config(state="normal")
        self.thread_text.delete("1.0", "end")
        header = f"From: {t['username']}"
        if t.get("server"):
            header += f"  ·  Server: {t['server']}"
        self.thread_text.insert("end", header + "\n", "meta")
        self.thread_text.insert("end", t["description"] + "\n\n")
        for c in t.get("comments", []):
            who = "You" if c["from"] == "owner" else t["username"]
            tag = "owner" if c["from"] == "owner" else "player"
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(c["at"]))
            self.thread_text.insert("end", f"[{ts}] {who}: ", tag)
            self.thread_text.insert("end", f"{c['message']}\n")
        self.thread_text.see("end")
        self.thread_text.config(state="disabled")

    def _selected_id(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Select a ticket first.", parent=self)
            return None
        return sel[0]

    def _add_comment(self):
        tid = self._selected_id()
        if not tid: return
        msg = _clean_ticket_text(self.v_comment.get(), TICKET_MESSAGE_MAX_LEN)
        if not msg: return
        with _tickets_lock:
            data = _load_tickets()
            for t in data["tickets"]:
                if t["ticket_id"] == tid:
                    t["comments"].append({"from":"owner","message":msg,"at":time.time()})
                    t["updated_at"] = time.time()
                    break
            _save_tickets(data)
        self.v_comment.set("")
        self._refresh()
        if self.tree.exists(tid):
            self.tree.selection_set(tid)
        self._on_select()

    def _resolve_ticket(self):
        tid = self._selected_id()
        if not tid: return
        if not messagebox.askyesno("Resolve Ticket",
                "Mark this ticket as resolved? The player will see it as closed "
                "the next time they open their ticket list.", parent=self):
            return
        with _tickets_lock:
            data = _load_tickets()
            for t in data["tickets"]:
                if t["ticket_id"] == tid:
                    t["status"]     = "closed"
                    t["closed_by"]  = "owner"
                    t["updated_at"] = time.time()
                    break
            _save_tickets(data)
        self._refresh()

