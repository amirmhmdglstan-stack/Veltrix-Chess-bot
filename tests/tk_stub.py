"""
tk_stub.py - headless tkinter stub for testing the Veltrix GUI logic.

This is NOT a general tkinter replacement - it implements just enough of the
Tk API for gui/app.py and friends to run without a display, so that game
flow, clock behaviour, engine event handling, PGN/FEN IO and configuration
can be tested in CI.

Dialogs can be auto-driven: a Toplevel's wait_window() invokes the first
"action" button (commands of Buttons whose text is in DIALOG_AUTO_ACTION).
"""
from __future__ import annotations

import sys
import types

_scheduled = []          # list of (ms, cb) pending callbacks
_clipboard = [""]
Font_Objects = []


class TclError(Exception):
    pass


def _pump(max_iter=10000):
    n = 0
    while _scheduled and n < max_iter:
        ms, cb = _scheduled.pop(0)
        try:
            cb()
        except Exception as exc:  # noqa: BLE001
            print(f"[tk_stub] scheduled callback crashed: {exc!r}")
            raise
        n += 1


class Widget:
    def __init__(self, master=None, **kw):
        self.master = master
        self._cfg = dict(kw)
        self._children = []
        self._binds = {}
        self._destroyed = False
        if master is not None and hasattr(master, "_children"):
            master._children.append(self)

    # geometry managers
    def pack(self, **kw): pass
    def grid(self, **kw): pass
    def place(self, **kw): pass
    def pack_forget(self): pass
    def grid_forget(self): pass

    def configure(self, **kw):
        self._cfg.update(kw)
    config = configure

    def cget(self, k):
        return self._cfg.get(k)

    def bind(self, ev, cb): self._binds[ev] = cb
    def unbind(self, ev): self._binds.pop(ev, None)

    def winfo_toplevel(self):
        w = self
        while getattr(w, "master", None) is not None:
            w = w.master
        return w

    def winfo_rootx(self): return 50
    def winfo_rooty(self): return 50
    def winfo_width(self): return int(str(self._cfg.get("width", 100)) or 100)
    def winfo_height(self): return int(str(self._cfg.get("height", 100)) or 100)
    def update_idletasks(self): pass
    def update(self): _pump()
    def grab_set(self): pass
    def grab_release(self): pass
    def transient(self, w): pass
    def withdraw(self): pass
    def deiconify(self): pass
    def geometry(self, g=None):
        if g:
            self._cfg["geometry"] = g
        return self._cfg.get("geometry", "100x100+0+0")

    def after(self, ms, cb=None):
        if cb is None:
            return
        _scheduled.append((ms, cb))
        return len(_scheduled)

    def after_cancel(self, job): pass

    def destroy(self):
        self._destroyed = True
        if self.master is not None and self in getattr(self.master, "_children", []):
            self.master._children.remove(self)
        for ch in list(self._children):
            ch.destroy()
        self._children.clear()

    def protocol(self, *a): pass
    def resizable(self, *a): pass
    def nametowidget(self, name): return self

    def grid_slaves(self): return list(self._children)


class Tk(Widget):
    def __init__(self, **kw):
        super().__init__(None, **kw)
        self.title_text = ""

    def title(self, t): self.title_text = t
    def mainloop(self): _pump()
    def clipboard_clear(self): _clipboard[0] = ""
    def clipboard_append(self, s): _clipboard[0] = s
    def clipboard_get(self): return _clipboard[0]


class Toplevel(Widget):
    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)

    def title(self, t): self._cfg["title"] = t

    def wait_window(self, w=None):
        # auto-drive: click every 'auto action' button in this dialog tree
        target = w or self
        def find(w):
            for ch in list(getattr(w, "_children", [])):
                if isinstance(ch, Button):
                    txt = str(ch._cfg.get("text", ""))
                    if txt in DIALOG_AUTO_ACTION or ch._cfg.get("_auto"):
                        ch.invoke()
                        return True
                if find(ch):
                    return True
            return False
        find(target)
        return


DIALOG_AUTO_ACTION = {"OK", "Start", "Cancel"}


class Canvas(Widget):
    _counter = [0]

    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self._items = {}
        self._pos = {}

    def create_rectangle(self, *a, **kw): return self._mk(**kw)
    def create_oval(self, *a, **kw): return self._mk(**kw)
    def create_text(self, *a, **kw): return self._mk(text=kw.get("text", ""))

    def _mk(self, **kw):
        Canvas._counter[0] += 1
        i = Canvas._counter[0]
        self._items[i] = kw
        return i

    def delete(self, tag): pass

    def coords(self, item, *xy):
        # real tk returns the item coords; keep a tiny per-item position so
        # animation math in board_widget can run headless
        if not xy:
            return self._pos.setdefault(item, [0.0, 0.0, 0.0, 0.0])
        cur = self._pos.setdefault(item, [0.0, 0.0, 0.0, 0.0])
        for i, v in enumerate(xy[:4]):
            cur[i] = float(v)
        return None

    def move(self, item, dx, dy):
        p = self._pos.setdefault(item, [0.0, 0.0, 0.0, 0.0])
        p[0] += dx
        p[1] += dy

    def tag_raise(self, item): pass
    def itemconfigure(self, item, **kw): self._items.setdefault(item, {}).update(kw)


class Label(Widget): pass
class Entry(Widget):
    def __init__(self, master=None, textvariable=None, **kw):
        super().__init__(master, **kw)
        self.tv = textvariable

    def get(self): return self.tv.get() if self.tv else ""
class LabelFrame(Widget): pass
class Frame(Widget):  # ttk.Frame alias also maps here
    pass


class Button(Widget):
    def __init__(self, master=None, command=None, **kw):
        super().__init__(master, **kw)
        self._command = command

    def invoke(self):
        if self._command:
            self._command()


class Checkbutton(Button):
    def __init__(self, master=None, variable=None, command=None, **kw):
        super().__init__(master, command=command, **kw)
        self.variable = variable

class Radiobutton(Widget):
    def __init__(self, master=None, variable=None, value=None, command=None, **kw):
        super().__init__(master, **kw)
        self.variable, self.value = variable, value
class Spinbox(Entry): pass
class Scale(Widget): pass


class Listbox(Widget):
    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self._items = []
        self._sel = {0}

    def insert(self, where, item):
        self._items.append(str(item))

    def curselection(self):
        return tuple(sorted(self._sel)) if self._sel else ()

    def selection_set(self, i): self._sel.add(i)
    def selection_clear(self, a, b=None): self._sel.clear()
    def see(self, i): pass
    def get(self, i): return self._items[i]


class Combobox(Widget):
    def __init__(self, master=None, textvariable=None, values=None, **kw):
        super().__init__(master, **kw)
        self.tv = textvariable
        self._cfg["values"] = values or []


class Text(Widget):
    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self._buf = []

    def insert(self, where, s):
        self._buf.append(str(s))

    def delete(self, a, b=None):
        self._buf.clear()

    def get(self, a, b=None):
        return "".join(self._buf)

    def index(self, where):
        if isinstance(where, str) and where.startswith("@"):
            return "1.0"
        return where if where else "end"

    def see(self, where): pass
    def tag_config(self, *a, **kw): pass
    def yview(self, *a): pass

    @property
    def content(self):
        return "".join(self._buf)


class Scrollbar(Widget):
    def __init__(self, master=None, command=None, **kw):
        super().__init__(master, **kw)
        self._command = command

    def set(self, *a): pass


class Canvas_:  # alias guard
    pass


class Menu(Widget):
    def __init__(self, master=None, tearoff=0, **kw):
        super().__init__(master, **kw)
        self._entries = []

    def add_command(self, **kw): self._entries.append(("command", kw))
    def add_checkbutton(self, **kw): self._entries.append(("checkbutton", kw))
    def add_cascade(self, **kw): self._entries.append(("cascade", kw))
    def add_radiobutton(self, **kw): self._entries.append(("radiobutton", kw))
    def add_separator(self, **kw): self._entries.append(("separator", kw))

    def insert_command(self, index, **kw):
        self._entries.insert(int(index) if index != "end" else len(self._entries),
                             ("command", kw))

    def index(self, label):
        for i, (t, kw) in enumerate(self._entries):
            if kw.get("label") == label:
                return i
        raise TclError(label)

    def entrycget(self, idx, key):
        return self._entries[int(idx)][1].get(key)


def nametowidget(name):
    return None


END = "end"
LEFT, RIGHT, BOTH, Y, X, TOP, BOTTOM, W, E, EW, NS, NSEW = \
    "left", "right", "both", "y", "x", "top", "bottom", "w", "e", "ew", "ns", "nsew"


class Variable:
    def __init__(self, master=None, value=None, **kw):
        self._v = value

    def set(self, v): self._v = v
    def get(self): return self._v


class StringVar(Variable): pass
class BooleanVar(Variable):
    def get(self): return bool(self._v)
class IntVar(Variable):
    def get(self): return int(self._v if self._v is not None else 0)
class DoubleVar(Variable):
    def get(self): return float(self._v if self._v is not None else 0.0)


# --- assemble fake tkinter module tree ---------------------------------------
def install():
    tk = types.ModuleType("tkinter")
    for name, obj in list(globals().items()):
        if name in ("Tk", "Toplevel", "Canvas", "Label", "Entry", "Button", "Frame",
                    "Checkbutton", "Radiobutton", "Spinbox", "Scale", "Listbox",
                    "Combobox", "Text", "Scrollbar", "Menu", "StringVar",
                    "BooleanVar", "IntVar", "DoubleVar", "Variable",
                    "LabelFrame", "TclError", "Widget", "nametowidget"):
            setattr(tk, name, obj)
        if name in ("LEFT", "RIGHT", "BOTH", "Y", "X", "TOP", "BOTTOM", "W", "E",
                    "EW", "NS", "NSEW", "END"):
            setattr(tk, name, obj)
    ttk = types.ModuleType("tkinter.ttk")
    for name in ("Frame", "Label", "Button", "Entry", "Checkbutton", "Combobox",
                 "LabelFrame", "Scrollbar", "Radiobutton", "Scale"):
        setattr(ttk, name, globals()[name])
    ttk.Spinbox = Spinbox
    filedialog = types.ModuleType("tkinter.filedialog")
    filedialog.asksaveasfilename = lambda **kw: STUB_DIALOG_ANSWERS.get("saveas", "")
    filedialog.askopenfilename = lambda **kw: STUB_DIALOG_ANSWERS.get("open", "")
    filedialog.askdirectory = lambda **kw: STUB_DIALOG_ANSWERS.get("dir", "")
    messagebox = types.ModuleType("tkinter.messagebox")
    messagebox.showinfo = lambda *a, **k: STUB_MESSAGES.append(("info", a[1] if len(a) > 1 else a))
    messagebox.showerror = lambda *a, **k: STUB_MESSAGES.append(("error", a[1] if len(a) > 1 else a))
    messagebox.showwarning = lambda *a, **k: STUB_MESSAGES.append(("warn", a[1] if len(a) > 1 else a))
    messagebox.askyesno = lambda *a, **k: True
    simpledialog = types.ModuleType("tkinter.simpledialog")
    simpledialog.askstring = lambda title, prompt, **kw: STUB_DIALOG_ANSWERS.get("string")
    simpledialog.askinteger = lambda title, prompt, **kw: STUB_DIALOG_ANSWERS.get("integer")
    simpledialog.askfloat = lambda title, prompt, **kw: STUB_DIALOG_ANSWERS.get("float")
    colorchooser = types.ModuleType("tkinter.colorchooser")
    colorchooser.askcolor = lambda *a, **k: STUB_DIALOG_ANSWERS.get("color")

    tk.ttk = ttk
    tk.filedialog = filedialog
    tk.messagebox = messagebox
    tk.simpledialog = simpledialog
    tk.colorchooser = colorchooser
    sys.modules["tkinter"] = tk
    sys.modules["tkinter.ttk"] = ttk
    sys.modules["tkinter.filedialog"] = filedialog
    sys.modules["tkinter.messagebox"] = messagebox
    sys.modules["tkinter.simpledialog"] = simpledialog
    sys.modules["tkinter.colorchooser"] = colorchooser
    return tk


STUB_DIALOG_ANSWERS = {}
STUB_MESSAGES = []
