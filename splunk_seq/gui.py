"""Desktop window: paste Input APIs, edit settings, run (standalone spec §8)."""

from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__
from .cli import load_input_apis
from .config import ConfigError, load_raw_or_default, save_config
from .form import CHANNEL_LABELS, FIELDS, form_to_raw, raw_to_form
from .job import JobResult, execute
from .paths import app_dir, resolve_in_app

CONFIG_NAME = "config.yaml"
EXAMPLE_NAME = "config.example.yaml"
LABEL_TO_CHANNEL = {label: value for value, label in CHANNEL_LABELS.items()}


def example_path() -> Path:
    """config.example.yaml beside the exe, else the copy bundled inside it."""
    local = app_dir() / EXAMPLE_NAME
    if local.exists() or not getattr(sys, "frozen", False):
        return local
    return Path(getattr(sys, "_MEIPASS", app_dir())) / EXAMPLE_NAME


class _Done:
    def __init__(self, result: JobResult):
        self.result = result


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.config_path = app_dir() / CONFIG_NAME
        raw, warning = load_raw_or_default(self.config_path, example_path())
        self.base = raw
        self.vars: dict[str, tk.Variable] = {}
        self.texts: dict[str, tk.Text] = {}
        self.editable: list[tk.Widget] = []
        self.stop_event = threading.Event()
        self.messages: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.closing = False

        root.title(f"Splunk API Sequence v{__version__}")
        root.geometry("900x820")
        self._build()
        self._fill(raw_to_form(raw))
        if warning:
            self.log(warning)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._poll)

    # ---- layout -------------------------------------------------------
    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, highlightthickness=0, height=470)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas)
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        apis = ttk.LabelFrame(body, text="Input APIs (one per line, # for comments)", padding=6)
        apis.pack(fill="x", pady=(0, 6))
        self.api_text = tk.Text(apis, height=6, width=80)
        self.api_text.pack(side="left", fill="x", expand=True)
        load = ttk.Button(apis, text="Load file…", command=self.load_file)
        load.pack(side="left", padx=(6, 0), anchor="n")
        self.editable += [self.api_text, load]

        main = ttk.LabelFrame(body, text="Settings", padding=6)
        main.pack(fill="x", pady=(0, 6))
        main.columnconfigure(1, weight=1)
        for row, field in enumerate(f for f in FIELDS if not f.advanced):
            self._add_field(main, row, field)

        self.adv_button = ttk.Button(body, text="Advanced ▸", command=self.toggle_advanced)
        self.adv_button.pack(anchor="w")
        self.advanced = ttk.Frame(body, padding=6)
        self.advanced.columnconfigure(1, weight=1)
        for row, field in enumerate(f for f in FIELDS if f.advanced):
            self._add_field(self.advanced, row, field)

        buttons = ttk.Frame(outer, padding=(0, 6))
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.save_button = ttk.Button(buttons, text="Save", command=self.save)
        self.run_button = ttk.Button(buttons, text="Run", command=self.run)
        self.stop_button = ttk.Button(buttons, text="Stop", command=self.stop, state="disabled")
        open_button = ttk.Button(buttons, text="Open output folder", command=self.open_output)
        for b in (self.save_button, self.run_button, self.stop_button, open_button):
            b.pack(side="left", padx=(0, 6))
        self.editable.append(self.save_button)

        self.log_pane = ScrolledText(outer, height=12, state="disabled")
        self.log_pane.grid(row=2, column=0, columnspan=2, sticky="nsew")

    def _add_field(self, parent: ttk.Frame, row: int, field) -> None:
        ttk.Label(parent, text=field.label).grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=2)
        if field.kind == "multiline":
            widget = tk.Text(parent, height=4, width=70)
            self.texts[field.key] = widget
        elif field.kind == "bool":
            var = tk.BooleanVar()
            widget = ttk.Checkbutton(parent, variable=var)
            self.vars[field.key] = var
        elif field.kind == "choice":
            var = tk.StringVar()
            widget = ttk.Combobox(parent, textvariable=var, values=list(CHANNEL_LABELS.values()), state="readonly", width=12)
            self.vars[field.key] = var
        else:
            var = tk.StringVar()
            self.vars[field.key] = var
            if field.kind in ("file", "dir"):
                widget = ttk.Frame(parent)
                entry = ttk.Entry(widget, textvariable=var)
                entry.pack(side="left", fill="x", expand=True)
                browse = ttk.Button(widget, text="Browse…", command=lambda: self.browse(field))
                browse.pack(side="left", padx=(6, 0))
                self.editable += [entry, browse]
            else:
                widget = ttk.Entry(parent, textvariable=var)
        sticky = "w" if field.kind in ("bool", "choice") else "ew"
        widget.grid(row=row, column=1, sticky=sticky, pady=2)
        if not isinstance(widget, ttk.Frame):
            self.editable.append(widget)

    # ---- form values --------------------------------------------------
    def _values(self) -> dict[str, str | bool]:
        values: dict[str, str | bool] = {}
        for field in FIELDS:
            if field.kind == "multiline":
                values[field.key] = self.texts[field.key].get("1.0", "end-1c")
            elif field.kind == "choice":
                label = self.vars[field.key].get()
                values[field.key] = LABEL_TO_CHANNEL.get(label, label)
            else:
                values[field.key] = self.vars[field.key].get()
        return values

    def _fill(self, values: dict[str, str | bool]) -> None:
        for field in FIELDS:
            value = values[field.key]
            if field.kind == "multiline":
                text = self.texts[field.key]
                text.delete("1.0", "end")
                text.insert("1.0", str(value).rstrip("\n"))
            elif field.kind == "choice":
                self.vars[field.key].set(CHANNEL_LABELS.get(str(value), str(value)))
            else:
                self.vars[field.key].set(value)

    # ---- actions ------------------------------------------------------
    def log(self, line: str) -> None:
        self.log_pane.configure(state="normal")
        self.log_pane.insert("end", line + "\n")
        self.log_pane.see("end")
        self.log_pane.configure(state="disabled")

    def toggle_advanced(self) -> None:
        if self.advanced.winfo_ismapped():
            self.advanced.pack_forget()
            self.adv_button.configure(text="Advanced ▸")
        else:
            self.advanced.pack(fill="x", after=self.adv_button)
            self.adv_button.configure(text="Advanced ▾")

    def browse(self, field) -> None:
        if field.kind == "dir":
            chosen = filedialog.askdirectory(initialdir=app_dir())
        else:
            chosen = filedialog.askopenfilename(initialdir=app_dir(), filetypes=[("PEM certificate", "*.pem *.crt"), ("All files", "*.*")])
        if chosen:
            self.vars[field.key].set(chosen)

    def load_file(self) -> None:
        chosen = filedialog.askopenfilename(filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not chosen:
            return
        try:
            text = Path(chosen).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            messagebox.showerror("Load file", f"Cannot read {chosen} (save it as UTF-8 text): {exc}")
            return
        self.api_text.delete("1.0", "end")
        self.api_text.insert("1.0", text)

    def save(self):
        raw = form_to_raw(self._values(), self.base)
        try:
            cfg = save_config(self.config_path, raw)
        except ConfigError as exc:
            messagebox.showerror("Settings", str(exc))
            return None
        self.base = raw
        self.log(f"Settings saved to {self.config_path}")
        return cfg

    def run(self) -> None:
        cfg = self.save()
        if cfg is None:
            return
        apis, skipped = load_input_apis(self.api_text.get("1.0", "end-1c"))
        if not apis:
            messagebox.showerror("Input APIs", "Paste at least one Input API (one per line) or use Load file…")
            return
        if skipped:
            self.log(f"Warning: {skipped} duplicate Input API line(s) skipped")
        self._set_running(True)
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._work, args=(cfg, apis), daemon=True)
        self.worker.start()

    def _work(self, cfg, apis: list[str]) -> None:
        try:
            result = execute(cfg, apis, self.messages.put, self.stop_event.is_set)
        except Exception:  # never let the worker die silently
            self.messages.put("Unexpected error:\n" + traceback.format_exc())
            result = JobResult(1, None, None)
        self.messages.put(_Done(result))

    def stop(self) -> None:
        self.stop_event.set()
        self.stop_button.configure(text="Stopping…", state="disabled")

    def open_output(self) -> None:
        folder = resolve_in_app(self._values()["output.dir"] or "output")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)
        except OSError as exc:
            messagebox.showerror("Open output folder", f"Cannot open {folder}: {exc}")

    def on_close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            if not messagebox.askyesno("Run in progress", "A run is in progress. Stop it and close?"):
                return
            self.closing = True
            self.stop()
            return
        self.root.destroy()

    # ---- worker plumbing ----------------------------------------------
    def _poll(self) -> None:
        try:
            while True:
                item = self.messages.get_nowait()
                if isinstance(item, _Done):
                    self._finish(item.result)
                else:
                    self.log(str(item))
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _finish(self, result: JobResult) -> None:
        self._set_running(False)
        if result.workbook_path is not None:
            self.log(f"Done. Workbook: {result.workbook_path}")
        if self.closing:
            self.root.destroy()

    def _set_running(self, running: bool) -> None:
        for widget in self.editable:
            if isinstance(widget, tk.Text):
                widget.configure(state="disabled" if running else "normal")
            else:
                widget.state(["disabled"] if running else ["!disabled"])
        self.run_button.state(["disabled"] if running else ["!disabled"])
        self.stop_button.configure(text="Stop", state="normal" if running else "disabled")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
