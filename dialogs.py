# dialogs.py
#
#   number_pad_dialog(parent, title)
#       Shows a modal number pad popup and returns the entered value
#       as a string, or None if the user cancelled / entered nothing.
#
#   show_message(parent, line1, line2)
#       Shows a simple two-line informational popup with an OK button.


import tkinter as tk
from tkinter import ttk
import time


def _modal_loop(parent, window):
    """
    Replacement for parent.wait_window(window).
    Keeps the Tkinter event loop alive so Wayland renders the window.
    """
    try:
        window.grab_set()
    except tk.TclError:
        pass   # grab can fail on Wayland — not fatal
    try:
        window.focus_force()
        window.lift()
        parent.update()
    except tk.TclError:
        return

    while True:
        try:
            if not window.winfo_exists():
                break
            parent.update()
        except tk.TclError:
            break
        time.sleep(0.02)


def number_pad_dialog(parent, title="Enter Value"):
    result = {"value": None}

    dialog = tk.Toplevel(parent)
    dialog.wm_attributes('-topmost', True)
    dialog.resizable(False, False)
    dialog.config(cursor="none")
    dialog.overrideredirect(True)

    w, h = 216, 400
    ws = parent.winfo_screenwidth()
    hs = parent.winfo_screenheight()
    dialog.geometry(f"{w}x{h}+{(ws//2)-(w//2)}+{(hs//2)-(h//2)}")
    dialog.config(bg="gray95")

    title_frame = tk.Frame(dialog, borderwidth=5, relief="ridge",
                           width=205, height=40, bg="gray95")
    title_lbl = tk.Label(title_frame, text=title, justify=tk.CENTER,
                         bg="gray95", font=("Times", 20))

    keypad_frame = ttk.Frame(dialog, borderwidth=5, relief="ridge",
                             width=205, height=300)

    entry_var = tk.StringVar()
    entry = tk.Entry(keypad_frame, textvariable=entry_var, font=("Times", 15))
    entry.grid(row=0, column=0, columnspan=3, ipady=5, sticky="NSEW")

    def on_key(value):
        if value == '<':
            entry_var.set(entry_var.get()[:-1])
        else:
            entry_var.set(entry_var.get() + value)

    keys = [
        ['1', '2', '3'],
        ['4', '5', '6'],
        ['7', '8', '9'],
        ['.', '0', '<'],
    ]
    for row_idx, row in enumerate(keys, start=1):
        for col_idx, key in enumerate(row):
            btn = tk.Button(keypad_frame, text=key, font=("Times", 22),
                            command=lambda v=key: on_key(v))
            btn.grid(row=row_idx, column=col_idx, ipadx=13, ipady=10)

    def on_save():
        val = entry_var.get().strip()
        if val:
            result["value"] = val
        dialog.destroy()

    save_btn = tk.Button(dialog, text="Save", relief="raised",
                         command=on_save, font=("Times", 20))

    dialog.columnconfigure(0, minsize=205)
    title_frame.grid(row=0, column=0, sticky="NSEW")
    title_lbl.pack()
    keypad_frame.grid(row=1, column=0, sticky="NSEW")
    save_btn.grid(row=2, column=0)

    _modal_loop(parent, dialog)
    return result["value"]


def show_message(parent, line1, line2=""):
    popup = tk.Toplevel(parent)
    popup.resizable(False, False)
    popup.overrideredirect(True)
    popup.config(cursor="none")

    w, h = 470, 170
    ws = parent.winfo_screenwidth()
    hs = parent.winfo_screenheight()
    popup.geometry(f"{w}x{h}+{(ws//2)-(w//2)}+{(hs//2)-(h//2)}")
    popup.config(bg="gray65")

    tk.Label(popup, text=line1, bg="gray65", font=('Times', 20)).pack()
    tk.Label(popup, text=line2, bg="gray65", font=('Times', 20)).pack()
    tk.Button(popup, text="OK", font=('Times', 20),
              command=popup.destroy).pack()

    _modal_loop(parent, popup)
