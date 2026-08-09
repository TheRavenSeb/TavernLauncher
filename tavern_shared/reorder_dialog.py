import tkinter as tk

from tavern_shared.theme import BG, SURF, SURF2, BORDER, AMBER, PARCH, MUTED, _btn, _mk_scrollbar
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window, _set_window_icon


class ReorderDialog(tk.Toplevel):
    """Lets the user drag... well, click Up/Down... to rearrange a list
    of {key, label} items from an OrderableRegistry, then save.
    """

    def __init__(self, parent, registry, title="Reorder", on_saved=None):
        super().__init__(parent)
        _start_hidden(self)
        self._registry = registry
        self._on_saved = on_saved
        self._title_text = title
        self.title(title)
        self.configure(bg=BG)
        self.resizable(True, True)
        _set_window_icon(self)

        self._keys = [item["key"] for item in registry.ordered_items()]
        self._labels = {item["key"]: item.get("label", item["key"]) for item in registry.all_items()}

        self._build()
        _finish_dark_window(self)
        self.update_idletasks()
        self.geometry(f"{max(360, self.winfo_reqwidth())}x{max(420, self.winfo_reqheight())}")

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text=f"↕  {self._title_text}", bg=SURF, fg=AMBER,
                 font=("Georgia", 12, "bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(self, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        self._listbox = tk.Listbox(body, bg=SURF, fg=PARCH, selectbackground=AMBER,
                                    selectforeground=SURF, relief="flat", bd=0,
                                    font=("Segoe UI", 10), activestyle="none")
        sb = _mk_scrollbar(body, self._listbox.yview)
        sb.pack(side="right", fill="y")
        self._listbox.config(yscrollcommand=sb.set)
        self._listbox.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self._refresh_listbox()

        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=16, pady=(0, 4))
        _btn(row, "▲ Up", lambda: self._move(-1), font=("Segoe UI", 9), pady=6, padx=12).pack(side="left")
        _btn(row, "▼ Down", lambda: self._move(1), font=("Segoe UI", 9), pady=6, padx=12).pack(side="left", padx=6)

        _btn(self, "Save Order", self._save, "primary",
             font=("Georgia", 10, "bold"), pady=10).pack(fill="x", padx=16, pady=(4, 16))

    def _refresh_listbox(self):
        self._listbox.delete(0, "end")
        for key in self._keys:
            self._listbox.insert("end", self._labels.get(key, key))

    def _move(self, delta):
        sel = self._listbox.curselection()
        if not sel:
            return
        i = sel[0]
        j = i + delta
        if j < 0 or j >= len(self._keys):
            return
        self._keys[i], self._keys[j] = self._keys[j], self._keys[i]
        self._refresh_listbox()
        self._listbox.selection_set(j)

    def _save(self):
        self._registry.save_order(self._keys)
        if self._on_saved:
            self._on_saved()
        self.destroy()
