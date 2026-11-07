"""A small college portal account manager with OS-protected encryption."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import sys
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from urllib.parse import urlsplit
import uuid
import webbrowser
from word_export import word_export
from version import VERSION

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
IS_MAC = sys.platform == "darwin"
VAULT = (Path.home() / "Library" / "Application Support" / "College Portals" / "accounts.vault"
         if IS_MAC else ROOT / "data" / "accounts.vault")
STATES = ("Not started", "Applied", "Awaiting decision", "Accepted", "Waitlisted", "Declined")


class EntryHistory:
    """Bounded per-field undo, cleared when a different account is loaded."""
    def __init__(self, variable):
        self.variable = variable
        self.suspended = False
        self.reset()
        variable.trace_add("write", self.record)

    def reset(self):
        self.states = [self.variable.get()]
        self.position = 0

    def record(self, *_):
        value = self.variable.get()
        if not self.suspended and value != self.states[self.position]:
            self.states = (self.states[:self.position + 1] + [value])[-101:]
            self.position = len(self.states) - 1

    def move(self, direction):
        position = self.position + direction
        if 0 <= position < len(self.states):
            self.position = position
            self.suspended = True
            try:
                self.variable.set(self.states[position])
            finally:
                self.suspended = False


def account_payload(payload):
    """Validate the entire file before using or saving any of its records."""
    if not isinstance(payload, dict) or payload.get("version") not in (1, 2):
        raise ValueError("Unsupported account file format")
    accounts = payload.get("accounts")
    fields = ("id", "college", "url", "username", "password", "status", "notes")
    if not isinstance(accounts, list) or any(
        not isinstance(a, dict) or any(not isinstance(a.get(k), str) for k in fields)
        for a in accounts
    ):
        raise ValueError("Invalid account data")
    if len({a["id"] for a in accounts}) != len(accounts):
        raise ValueError("Duplicate account identifiers")
    result = []
    for original in accounts:
        account = {k: original[k] for k in fields}
        account["email"] = original.get("email", account["username"] if payload["version"] == 1 and "@" in account["username"] else "")
        account["applicant_id"] = original.get("applicant_id", "")
        if any(not isinstance(account[k], str) for k in ("email", "applicant_id")):
            raise ValueError("Invalid account data")
        if payload["version"] == 2 and any(k not in original for k in ("email", "applicant_id")):
            raise ValueError("Missing email or applicant ID field")
        if not account["id"] or not account["college"].strip():
            raise ValueError("Each account needs an identifier and college name")
        account["url"] = portal_url(account["url"])
        result.append(account)
    return result


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".college-", delete=False) as file:
            temporary = Path(file.name)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def readable_export(accounts, profile_name):
    lines = ["COLLEGE PORTALS", f"Profile: {profile_name}", f"Saved accounts: {len(accounts)}",
             "Contains readable passwords. Keep this file private.", ""]
    for number, account in enumerate(sorted(accounts, key=lambda a: a["college"].casefold()), 1):
        lines.extend(["=" * 64, f"{number}. {account['college']}", "=" * 64])
        for key, label in (("url", "Portal address"), ("email", "Email"), ("username", "Username"),
                           ("applicant_id", "Applicant / student ID"), ("password", "Password"),
                           ("status", "Application status")):
            lines.append(f"{label}: {account[key]}")
        lines.extend(["Notes:", account["notes"], ""])
    if not accounts:
        lines.append("No saved accounts in this profile.")
    return "\n".join(lines)


class Profiles:
    """Local record separation only; every profile uses the same OS login."""
    def __init__(self, default_vault):
        self.default_vault = default_vault
        self.catalog = default_vault.parent / "profiles.json"
        self.items = [{"id": "default", "name": "Default"}]
        if self.catalog.exists():
            items = json.loads(self.catalog.read_text(encoding="utf-8"))
            if not isinstance(items, list) or not items or items[0] != self.items[0]:
                raise ValueError("Invalid profile list")
            names, ids = set(), set()
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
                    raise ValueError("Invalid profile name")
                key = item.get("id")
                if key != "default" and (not isinstance(key, str) or str(uuid.UUID(key)) != key):
                    raise ValueError("Invalid profile identifier")
                if key in ids or item["name"].casefold() in names:
                    raise ValueError("Duplicate profile")
                ids.add(key)
                names.add(item["name"].casefold())
            self.items = items

    def store_for(self, key):
        if not any(p["id"] == key for p in self.items):
            raise ValueError("Unknown profile")
        return Store(self.default_vault if key == "default" else self.default_vault.parent / "profiles" / f"{key}.vault")

    def create(self, name):
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("Enter a profile name between 1 and 80 characters")
        if any(p["name"].casefold() == name.casefold() for p in self.items):
            raise ValueError("A profile with that name already exists")
        item = {"id": str(uuid.uuid4()), "name": name}
        updated = self.items + [item]
        atomic_write(self.catalog, json.dumps(updated, ensure_ascii=False, indent=2).encode("utf-8"))
        self.items = updated
        return item


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data: bytes, decrypt: bool = False) -> bytes:
    """DPAPI binds the vault to the current Windows user's credentials."""
    if IS_MAC:
        from mac_crypto import mac_crypt
        return mac_crypt(data, decrypt)
    if os.name != "nt":
        raise OSError("This app requires Windows to encrypt your accounts.")
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    result = Blob()
    dll = ctypes.WinDLL("crypt32", use_last_error=True)
    free = ctypes.WinDLL("kernel32", use_last_error=True).LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    if decrypt:
        fn = dll.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        args = (ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    else:
        fn = dll.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        args = (ctypes.byref(source), "College portal accounts", None, None, None, 1, ctypes.byref(result))
    fn.restype = wintypes.BOOL
    if not fn(*args):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        free(ctypes.cast(result.data, ctypes.c_void_p))


class Store:
    def __init__(self, path: Path = VAULT):
        self.path = path

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        return account_payload(json.loads(crypt(self.path.read_bytes(), decrypt=True)))

    def save(self, accounts: list[dict]):
        encrypted = crypt(json.dumps({"version": 2, "accounts": accounts}).encode("utf-8"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        try:
            with temporary.open("wb") as file:
                file.write(encrypted)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


def portal_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    parts = urlsplit(value)
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Enter a portal address such as https://admissions.example.edu.")
    if any(c.isspace() for c in value):
        raise ValueError("Portal addresses cannot contain spaces.")
    # Accessing port also validates malformed port numbers.
    _ = parts.port
    return value


class App(tk.Tk):
    def __init__(self, store: Store | None = None):
        super().__init__()
        self.title(f"College Portals {VERSION}")
        self.geometry("1000x740")
        self.minsize(850, 680)
        self.configure(bg="#f5f6f8")
        self.store = store or Store()
        self.active_profile = "default"
        self.current = None
        self.baseline = None
        self.clipboard_timer = None
        self.copied_value = None
        self.reveal_timer = None
        self.protocol("WM_DELETE_WINDOW", self.close)
        try:
            self.profiles = Profiles(self.store.path)
            self.accounts = self.store.load()
        except Exception:
            self.withdraw()
            messagebox.showerror("Could not open accounts", "Your account file could not be read or decrypted. "
                                 "It has been left untouched. " +
                                 ("Check access to your login Keychain and the original Mac encryption key. "
                                  "Windows vaults cannot be opened on a Mac." if IS_MAC else
                                  "Open it with the Windows account that created it, or restore a working backup."), parent=self)
            self.destroy()
            raise SystemExit(1)
        self.setup_style()
        self.build()
        self.refresh()
        self.load_account(None)

    def setup_style(self):
        self.font_family = "Helvetica Neue" if IS_MAC else "Segoe UI"
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f5f6f8")
        style.configure("TLabel", background="#f5f6f8", foreground="#263244", font=(self.font_family, 10))
        style.configure("Title.TLabel", font=(self.font_family, 23, "bold"))
        style.configure("Heading.TLabel", font=(self.font_family, 15, "bold"))
        style.configure("Muted.TLabel", foreground="#667085", font=(self.font_family, 9))
        style.configure("TButton", font=(self.font_family, 10), padding=(12, 5))
        style.configure("Primary.TButton", foreground="white", background="#3159cc")
        style.map("Primary.TButton", background=[("active", "#2446ac")])
        style.configure("TEntry", padding=6, font=(self.font_family, 10))
        style.configure("TCombobox", padding=5, font=(self.font_family, 10))
        style.configure("Treeview", rowheight=48, font=(self.font_family, 11), borderwidth=0,
                        background="white", fieldbackground="white")
        style.map("Treeview", background=[("selected", "#e4ebff")], foreground=[("selected", "#183a96")])

    def build(self):
        shell = ttk.Frame(self, padding=28)
        shell.pack(fill="both", expand=True)
        top = ttk.Frame(shell)
        top.pack(fill="x")
        ttk.Label(top, text="College Portals", style="Title.TLabel").pack(side="left")
        ttk.Button(top, text="+  Add college", style="Primary.TButton", command=self.new).pack(side="right")
        self.export_button = ttk.Button(top, text="Export all ▾", command=self.show_export_menu)
        self.export_button.pack(side="right", padx=(0, 8))
        self.export_menu = tk.Menu(self.export_button, tearoff=False)
        self.export_menu.add_command(label="JSON (for import / backup)", command=self.export_all)
        self.export_menu.add_command(label="Readable text (.txt)", command=lambda: self.export_all("txt"))
        self.export_menu.add_command(label="Word document (.docx)", command=lambda: self.export_all("docx"))
        self.import_button = ttk.Button(top, text="Import", command=self.import_accounts)
        self.import_button.pack(side="right", padx=(0, 8))
        self.profile_label = ttk.Label(shell, text="Active account: Default", style="Muted.TLabel")
        self.profile_label.pack(anchor="w", pady=(4, 10))
        self.tabs = ttk.Notebook(shell)
        self.tabs.pack(fill="both", expand=True)
        self.portals_tab = ttk.Frame(self.tabs, padding=(0, 10))
        switch_tab = ttk.Frame(self.tabs, padding=20)
        self.tabs.add(self.portals_tab, text="Portals")
        self.tabs.add(switch_tab, text="Account switch")
        ttk.Label(switch_tab, text="Local accounts", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(switch_tab, text="Each profile has its own college records. Switch freely; no login is required.").pack(anchor="w", pady=(8, 16))
        self.profile_tree = ttk.Treeview(switch_tab, show="tree", selectmode="browse", height=5)
        self.profile_tree.pack(fill="both", expand=True)
        self.profile_tree.bind("<Double-1>", lambda _: self.switch_selected_profile())
        profile_actions = ttk.Frame(switch_tab)
        profile_actions.pack(fill="x", pady=(12, 0))
        ttk.Button(profile_actions, text="Create account", command=self.create_profile).pack(side="left")
        ttk.Button(profile_actions, text="Switch to selected", style="Primary.TButton", command=self.switch_selected_profile).pack(side="right")
        self.refresh_profiles()
        body = ttk.Frame(self.portals_tab)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=2, minsize=260)
        body.columnconfigure(1, weight=3, minsize=440)
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 28))
        self.search = tk.StringVar()
        ttk.Label(left, text="FIND A COLLEGE", style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        search_entry = ttk.Entry(left, textvariable=self.search)
        self.search_entry = search_entry
        search_entry.pack(fill="x")
        self.add_edit_menu(search_entry, self.search)
        self.search.trace_add("write", lambda *_: self.refresh())
        self.count = ttk.Label(left, style="Muted.TLabel")
        self.count.pack(anchor="w", pady=(14, 8))
        list_frame = ttk.Frame(left)
        list_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(list_frame, show="tree", selectmode="browse", height=5)
        self.tree.column("#0", width=240, stretch=True)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.select)
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        self.heading = ttk.Label(right, text="Add your first college", style="Heading.TLabel")
        self.heading.pack(anchor="w", pady=(0, 8))
        # Keep actions visible while the form scrolls on smaller screens.
        actions = ttk.Frame(right)
        actions.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(actions, text="Save account", style="Primary.TButton", command=self.save).pack(side="left")
        self.delete_button = ttk.Button(actions, text="Delete", command=self.delete)
        self.delete_button.pack(side="right")
        viewport = ttk.Frame(right)
        viewport.pack(fill="both", expand=True)
        self.form_canvas = tk.Canvas(viewport, background="#f5f6f8", highlightthickness=0, width=1, height=1)
        form_scroll = ttk.Scrollbar(viewport, orient="vertical", command=self.form_canvas.yview)
        self.form_canvas.configure(yscrollcommand=form_scroll.set)
        form_scroll.pack(side="right", fill="y")
        self.form_canvas.pack(side="left", fill="both", expand=True)
        form = ttk.Frame(self.form_canvas)
        form_window = self.form_canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda _: self.form_canvas.configure(scrollregion=self.form_canvas.bbox("all")))
        self.form_canvas.bind("<Configure>", lambda e: self.form_canvas.itemconfigure(form_window, width=e.width))
        self.fields = {key: tk.StringVar() for key in ("college", "url", "email", "username", "applicant_id", "password", "status")}
        self.entries = {}
        self.paste_buttons = {}
        for key, label in (("college", "College name *"), ("url", "Portal address"),
                           ("email", "Email"), ("username", "Username"),
                           ("applicant_id", "Applicant / student ID"), ("password", "Password")):
            ttk.Label(form, text=label).pack(anchor="w", pady=(0, 3))
            row = ttk.Frame(form)
            row.pack(fill="x", pady=(0, 8))
            entry = ttk.Entry(row, width=12, textvariable=self.fields[key], show="•" if key == "password" else "")
            entry.pack(side="left", fill="x", expand=True)
            self.entries[key] = entry
            self.add_edit_menu(entry, self.fields[key])
            paste = ttk.Button(row, text="Paste", width=5, command=lambda w=entry: self.paste(w))
            paste.pack(side="left", padx=(6, 0))
            self.paste_buttons[key] = paste
            if key == "url":
                ttk.Button(row, text="Open", width=5, command=self.open_portal).pack(side="left", padx=(6, 0))
            if key in ("email", "username", "applicant_id", "password"):
                ttk.Button(row, text="Copy", width=5, command=lambda k=key: self.copy(k)).pack(side="right", padx=(6, 0))
            if key == "password":
                self.show_button = ttk.Button(row, text="Show", width=5, command=self.toggle_password)
                self.show_button.pack(side="left", padx=(6, 0))
        ttk.Label(form, text="Application status").pack(anchor="w", pady=(0, 3))
        ttk.Combobox(form, textvariable=self.fields["status"], values=STATES, state="readonly").pack(fill="x", pady=(0, 8))
        notes_heading = ttk.Frame(form)
        notes_heading.pack(fill="x", pady=(0, 3))
        ttk.Label(notes_heading, text="Notes").pack(side="left")
        ttk.Button(notes_heading, text="Paste", width=5, command=lambda: self.paste(self.notes)).pack(side="right")
        self.notes = tk.Text(form, height=4, width=20, font=(self.font_family, 10), wrap="word", relief="solid",
                             borderwidth=1, padx=10, pady=8, background="white", undo=True)
        self.notes.pack(fill="x")
        self.add_edit_menu(self.notes)
        def scroll_form(event):
            delta = -int(event.delta) if IS_MAC else -int(event.delta / 120)
            self.form_canvas.yview_scroll(delta, "units")
            return "break"
        def bind_scroll(widget):
            if widget is not self.notes:
                widget.bind("<MouseWheel>", scroll_form)
            if isinstance(widget, (ttk.Entry, ttk.Combobox, tk.Text)):
                widget.bind("<FocusIn>", lambda _, w=widget: self.show_field(w))
            for child in widget.winfo_children():
                bind_scroll(child)
        bind_scroll(form)
        self.form_canvas.bind("<MouseWheel>", scroll_form)
        self.feedback = ttk.Label(shell, text="Ready to add your first college.", style="Muted.TLabel")
        self.feedback.pack(anchor="w", pady=(12, 4))
        protection = "Protected by macOS Keychain" if IS_MAC else "Encrypted for your Windows login"
        ttk.Label(shell, text=f"Stored locally • {protection} • Copied text clears after 30 seconds",
                  style="Muted.TLabel").pack(anchor="w")
        self.bind("<Control-s>", lambda _: self.save())
        self.bind("<Control-n>", lambda _: self.new())
        if IS_MAC:
            self.bind("<Command-s>", lambda _: self.save())
            self.bind("<Command-n>", lambda _: self.new())
            self.createcommand("tk::mac::Quit", self.close)

    def form(self):
        return {**{k: v.get() for k, v in self.fields.items()}, "notes": self.notes.get("1.0", "end-1c")}

    def refresh_profiles(self):
        self.profile_tree.delete(*self.profile_tree.get_children())
        for profile in self.profiles.items:
            self.profile_tree.insert("", "end", iid=profile["id"], text=profile["name"])
        self.profile_tree.selection_set(self.active_profile)

    def profile_name(self):
        return next(p["name"] for p in self.profiles.items if p["id"] == self.active_profile)

    def create_profile(self):
        name = simpledialog.askstring("Create local account", "Account / profile name:", parent=self)
        if name is None:
            return
        try:
            item = self.profiles.create(name)
        except (OSError, ValueError) as error:
            messagebox.showerror("Could not create account", str(error), parent=self)
            return
        self.refresh_profiles()
        self.profile_tree.selection_set(item["id"])
        self.switch_profile(item["id"])

    def switch_selected_profile(self):
        selected = self.profile_tree.selection()
        if selected:
            self.switch_profile(selected[0])

    def switch_profile(self, key):
        if key == self.active_profile:
            self.tabs.select(self.portals_tab)
            return True
        if not self.may_leave():
            return False
        try:
            store = self.profiles.store_for(key)
            accounts = store.load()
        except Exception as error:
            messagebox.showerror("Could not switch account", "The selected account could not be opened. Your current account is unchanged.\n" + str(error), parent=self)
            return False
        self.clear_copied()
        self.store, self.accounts, self.active_profile = store, accounts, key
        self.load_account(None)
        self.search.set("")
        self.search_entry.history.reset()
        self.refresh()
        self.refresh_profiles()
        self.profile_label.configure(text=f"Active account: {self.profile_name()}")
        self.title(f"College Portals {VERSION} — {self.profile_name()}")
        self.feedback.configure(text=f"Switched to {self.profile_name()}.")
        self.tabs.select(self.portals_tab)
        return True

    def import_accounts(self):
        if not self.may_leave():
            return
        filename = filedialog.askopenfilename(parent=self, title=f"Import accounts into {self.profile_name()}",
                                              filetypes=[("JSON account export", "*.json")])
        if not filename:
            return
        try:
            incoming = account_payload(json.loads(Path(filename).read_text(encoding="utf-8-sig")))
            updated = list(self.accounts)
            def signature(account):
                return tuple((k, account[k]) for k in sorted(account) if k != "id")
            seen = {signature(a) for a in updated}
            identifiers = {a["id"] for a in updated}
            added = 0
            for account in incoming:
                value = signature(account)
                if value in seen:
                    continue
                if account["id"] in identifiers:
                    account["id"] = str(uuid.uuid4())
                updated.append(account)
                identifiers.add(account["id"])
                seen.add(value)
                added += 1
            if added:
                self.store.save(updated)
        except Exception as error:
            messagebox.showerror("Could not import", "No accounts were imported.\n" + str(error), parent=self)
            return
        self.accounts = updated
        # Preserve an unsaved form when the user chose not to save it.
        self.refresh()
        self.feedback.configure(text=f"Imported {added} accounts into {self.profile_name()}; skipped {len(incoming) - added} duplicates.")
        messagebox.showinfo("Import complete", f"Added {added} accounts to {self.profile_name()}.\n"
                            f"Skipped {len(incoming) - added} duplicates. Existing accounts were kept.", parent=self)

    def add_edit_menu(self, widget, variable=None):
        if variable is not None:
            widget.history = EntryHistory(variable)
        menu = tk.Menu(widget, tearoff=False)
        menu.add_command(label="Undo", command=lambda: self.undo_edit(widget))
        menu.add_command(label="Redo", command=lambda: self.undo_edit(widget, redo=True))
        menu.add_separator()
        for label, event in (("Cut", "<<Cut>>"), ("Copy", "<<Copy>>"), ("Paste", "<<Paste>>")):
            menu.add_command(label=label, command=lambda e=event: widget.event_generate(e))
        menu.add_separator()
        menu.add_command(label="Select all", command=lambda: self.select_all(widget))
        def popup(event):
            widget.focus_set()
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
            return "break"
        widget.bind("<Button-3>", popup)
        widget.bind("<<Paste>>", lambda _: self.paste(widget))
        widget.bind("<<Copy>>", lambda _: self.copy_selection(widget))
        widget.bind("<<Cut>>", lambda _: self.copy_selection(widget, cut=True))
        widget.bind("<Control-a>", lambda _: self.select_all(widget))
        widget.bind("<Control-A>", lambda _: self.select_all(widget))
        widget.bind("<<Undo>>", lambda _: self.undo_edit(widget))
        widget.bind("<<Redo>>", lambda _: self.undo_edit(widget, redo=True))
        for shortcut in ("<Control-z>", "<Control-Z>"):
            widget.bind(shortcut, lambda _: self.undo_edit(widget))
        for shortcut in ("<Control-y>", "<Control-Y>", "<Control-Shift-z>", "<Control-Shift-Z>"):
            widget.bind(shortcut, lambda _: self.undo_edit(widget, redo=True))
        if IS_MAC:
            widget.bind("<Button-2>", popup)
            widget.bind("<Control-Button-1>", popup)
            widget.bind("<Command-a>", lambda _: self.select_all(widget))
            widget.bind("<Command-v>", lambda _: self.paste(widget))
            widget.bind("<Command-c>", lambda _: self.copy_selection(widget))
            widget.bind("<Command-x>", lambda _: self.copy_selection(widget, cut=True))
            widget.bind("<Command-z>", lambda _: self.undo_edit(widget))
            widget.bind("<Command-Shift-z>", lambda _: self.undo_edit(widget, redo=True))
            widget.bind("<Command-Shift-Z>", lambda _: self.undo_edit(widget, redo=True))

    def undo_edit(self, widget, redo=False):
        if isinstance(widget, tk.Text):
            try:
                widget.edit_redo() if redo else widget.edit_undo()
            except tk.TclError:
                pass  # No history is a normal state, not an error dialog.
        else:
            widget.history.move(1 if redo else -1)
            widget.icursor("end")
            widget.selection_clear()
        return "break"

    def select_all(self, widget):
        if isinstance(widget, tk.Text):
            widget.tag_add("sel", "1.0", "end-1c")
        else:
            widget.selection_range(0, "end")
            widget.icursor("end")
        return "break"

    def show_field(self, widget):
        canvas = self.form_canvas
        height = canvas.winfo_height()
        top = widget.winfo_rooty() - canvas.winfo_rooty()
        bottom = top + widget.winfo_height()
        region = canvas.bbox("all")
        if region and region[3] > height:
            if top < 0:
                canvas.yview_moveto(max(0, (canvas.canvasy(0) + top) / region[3]))
            elif bottom > height:
                canvas.yview_moveto((canvas.canvasy(0) + bottom - height) / region[3])

    def copy_selection(self, widget, cut=False):
        try:
            if not isinstance(widget, tk.Text) and not widget.selection_present():
                return "break"
            value = widget.get("sel.first", "sel.last") if isinstance(widget, tk.Text) else widget.selection_get()
        except tk.TclError:
            return "break"
        self.copy_text(value)
        if cut:
            widget.delete("sel.first", "sel.last")
        return "break"

    def paste(self, widget):
        try:
            value = self.clipboard_get()
        except tk.TclError:
            self.feedback.configure(text="The clipboard has no text to paste.")
            return "break"
        widget.focus_set()
        if isinstance(widget, tk.Text):
            widget.edit_separator()
            auto = widget.cget("autoseparators")
            widget.configure(autoseparators=False)
            try:
                if widget.tag_ranges("sel"):
                    widget.delete("sel.first", "sel.last")
                widget.insert("insert", value)
            finally:
                widget.configure(autoseparators=auto)
            widget.edit_separator()
        else:
            # Replacing a selection is one edit, rather than delete + insert.
            widget.history.suspended = True
            try:
                if widget.selection_present():
                    widget.delete("sel.first", "sel.last")
                widget.insert("insert", value)
            finally:
                widget.history.suspended = False
                widget.history.record()
        self.feedback.configure(text="Pasted text. Save account to keep changes.")
        return "break"

    def may_leave(self):
        if self.baseline == self.form():
            return True
        result = messagebox.askyesnocancel("Unsaved changes", "Save your changes before continuing?", parent=self)
        return self.save() if result else result is False

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        query = self.search.get().strip().casefold()
        matches = [a for a in self.accounts if query in " ".join(
            a[k] for k in ("college", "email", "username", "applicant_id")).casefold()]
        for a in sorted(matches, key=lambda a: a["college"].casefold()):
            self.tree.insert("", "end", iid=a["id"], text=a["college"])
        self.count.configure(text=f"{len(matches)} of {len(self.accounts)} colleges" if query else f"{len(self.accounts)} colleges")
        if self.current and self.tree.exists(self.current):
            self.tree.selection_set(self.current)

    def load_account(self, account):
        self.hide_password()
        self.current = account["id"] if account else None
        for key, variable in self.fields.items():
            variable.set(account[key] if account else (STATES[0] if key == "status" else ""))
        for entry in self.entries.values():
            entry.history.reset()
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", account["notes"] if account else "")
        self.notes.edit_reset()
        self.heading.configure(text="Account details" if account else "Add a college")
        self.delete_button.configure(state="normal" if account else "disabled")
        self.baseline = self.form()
        self.form_canvas.yview_moveto(0)

    def select(self, _=None):
        selected = self.tree.selection()
        if not selected or selected[0] == self.current:
            return
        target = selected[0]
        if not self.may_leave():
            self.tree.selection_remove(*self.tree.selection())
            if self.current and self.tree.exists(self.current):
                self.tree.selection_set(self.current)
            return
        account = next((a for a in self.accounts if a["id"] == target), None)
        if account:
            self.load_account(account)
            if self.tree.exists(target):
                self.tree.selection_set(target)

    def new(self):
        if self.may_leave():
            self.tree.selection_remove(*self.tree.selection())
            self.load_account(None)
            self.entries["college"].focus_set()

    def save(self):
        account = self.form()
        account["college"] = account["college"].strip()
        if not account["college"]:
            messagebox.showwarning("College name required", "Enter a college name to save this account.", parent=self)
            self.entries["college"].focus_set()
            return False
        try:
            account["url"] = portal_url(account["url"])
        except ValueError as error:
            messagebox.showwarning("Check portal address", str(error), parent=self)
            return False
        account["id"] = self.current or str(uuid.uuid4())
        updated = [a for a in self.accounts if a["id"] != account["id"]] + [account]
        try:
            self.store.save(updated)
        except Exception:
            messagebox.showerror("Could not save", "Your changes were not saved. Check that the data folder is writable and try again.", parent=self)
            return False
        self.accounts = updated
        self.load_account(account)
        self.refresh()
        self.feedback.configure(text=f"Saved {account['college']}.")
        return True

    def show_export_menu(self):
        try:
            self.export_menu.tk_popup(self.export_button.winfo_rootx(),
                                      self.export_button.winfo_rooty() + self.export_button.winfo_height())
        finally:
            self.export_menu.grab_release()

    def export_all(self, file_format="json"):
        if not self.may_leave():
            return
        formats = {"json": "JSON account export", "txt": "Readable text", "docx": "Word document"}
        if file_format not in formats:
            return
        filename = filedialog.asksaveasfilename(
            parent=self, title=f"Export {self.profile_name()} — includes readable passwords",
            initialfile=f"college-accounts.{file_format}", defaultextension=f".{file_format}",
            filetypes=[(formats[file_format], f"*.{file_format}")])
        if not filename:
            return
        destination = Path(filename)
        try:
            protected = [self.profiles.catalog] + [self.profiles.store_for(p["id"]).path for p in self.profiles.items]
            if destination.resolve() in [p.resolve() for p in protected]:
                raise ValueError("Choose a different file from the encrypted account vault.")
            if file_format == "docx":
                data = word_export(self.accounts, self.profile_name())
            else:
                payload = (readable_export(self.accounts, self.profile_name()) if file_format == "txt" else
                           json.dumps({"version": 2, "accounts": self.accounts}, ensure_ascii=False, indent=2))
                data = (payload + "\n").encode("utf-8")
            atomic_write(destination, data)
        except (OSError, ValueError) as error:
            messagebox.showerror("Could not export", str(error), parent=self)
            return
        self.feedback.configure(text=f"Exported {len(self.accounts)} saved accounts. This file contains readable passwords.")
        messagebox.showinfo("Export complete", f"Exported {len(self.accounts)} saved accounts to:\n{destination}\n\n"
                            "This file contains readable passwords. Keep it somewhere private.", parent=self)

    def delete(self):
        if not self.current:
            return
        name = next(a["college"] for a in self.accounts if a["id"] == self.current)
        if not messagebox.askyesno("Delete account?", f"Permanently delete the saved account for {name}?", parent=self):
            return
        updated = [a for a in self.accounts if a["id"] != self.current]
        try:
            self.store.save(updated)
        except Exception:
            messagebox.showerror("Could not delete", "The account was not deleted. Check that the data folder is writable.", parent=self)
            return
        self.accounts = updated
        self.load_account(None)
        self.refresh()
        self.feedback.configure(text=f"Deleted {name}.")

    def hide_password(self):
        if self.reveal_timer:
            self.after_cancel(self.reveal_timer)
            self.reveal_timer = None
        self.entries["password"].configure(show="•")
        self.show_button.configure(text="Show")

    def toggle_password(self):
        if self.entries["password"].cget("show"):
            self.entries["password"].configure(show="")
            self.show_button.configure(text="Hide")
            self.reveal_timer = self.after(15000, self.hide_password)
        else:
            self.hide_password()

    def copy(self, key):
        value = self.fields[key].get()
        if not value:
            self.feedback.configure(text=f"No {key} to copy yet.")
            return
        self.copy_text(value)
        self.feedback.configure(text=f"Copied {key}. Clipboard will clear in 30 seconds.")

    def copy_text(self, value):
        self.clipboard_clear()
        self.clipboard_append(value)
        self.copied_value = value
        if self.clipboard_timer:
            self.after_cancel(self.clipboard_timer)
        self.clipboard_timer = self.after(30000, self.clear_copied)
        self.feedback.configure(text="Copied text. Clipboard will clear in 30 seconds.")

    def clear_copied(self):
        if self.clipboard_timer:
            self.after_cancel(self.clipboard_timer)
        try:
            if self.copied_value is not None and self.clipboard_get() == self.copied_value:
                self.clipboard_clear()
        except tk.TclError:
            pass
        self.copied_value = None
        self.clipboard_timer = None

    def open_portal(self):
        try:
            url = portal_url(self.fields["url"].get())
            if not url:
                raise ValueError("Add a portal address first.")
            if not webbrowser.open(url):
                raise ValueError("Could not open your browser. Copy the portal address into your browser.")
        except (ValueError, OSError) as error:
            messagebox.showwarning("Could not open portal", str(error), parent=self)

    def close(self):
        if self.may_leave():
            self.clear_copied()
            self.destroy()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from frozen_check import self_test
        self_test(Path(sys.argv[2]))
    else:
        App().mainloop()
