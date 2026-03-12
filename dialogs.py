# dialogs.py
#
#   number_pad_dialog(parent, title)
#       Shows a modal number pad popup and returns the entered value
#       as a string, or None if the user cancelled / entered nothing.
#
#   show_message(parent, line1, line2)
#       Shows a simple two line informational popup with an OK button.

import tkinter as tk
from tkinter import ttk


# ---------------------------------------------------------------------------
# Number pad dialog
# ---------------------------------------------------------------------------

def number_pad_dialog(parent, title="Enter Value"):
    """
    Display a modal number-pad popup centred on the screen.

    Parameters
    ----------
    parent : tk.Tk or tk.Toplevel
        The parent window.
    title : str
        Heading text shown above the entry field.

    Returns
    -------
    str or None
        The string entered by the user, or None if nothing was entered
        or the dialog was dismissed without saving.
    """

    result = {"value": None}  # mutable container so the inner function can write to it

    dialog = tk.Toplevel(parent)
    dialog.wm_attributes('-topmost', True)
    dialog.resizable(False, False)
    dialog.config(cursor="none")
    dialog.overrideredirect(True)

    # --- layout constants ---
    w, h = 216, 400
    ws = parent.winfo_screenwidth()
    hs = parent.winfo_screenheight()
    x  = (ws // 2) - (w // 2)
    y  = (hs // 2) - (h // 2)
    dialog.geometry(f"{w}x{h}+{x}+{y}")
    dialog.config(bg="gray95")

    # --- title bar ---
    title_frame = tk.Frame(dialog, borderwidth=5, relief="ridge",
                           width=205, height=40, bg="gray95")
    title_lbl = tk.Label(title_frame, text=title, justify=tk.CENTER,
                         bg="gray95", font=("Times", 20))

    # --- entry display ---
    keypad_frame = ttk.Frame(dialog, borderwidth=5, relief="ridge",
                             width=205, height=300)

    entry_var = tk.StringVar()
    entry = tk.Entry(keypad_frame, textvariable=entry_var, font=("Times", 15))
    entry.grid(row=0, column=0, columnspan=3, ipady=5, sticky="NSEW")

    # --- key press handler ---
    def on_key(value):
        if value == '<':
            current = entry_var.get()
            entry_var.set(current[:-1])
        else:
            entry_var.set(entry_var.get() + value)

    # --- build number pad buttons ---
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

    # --- save button ---
    def on_save():
        val = entry_var.get().strip()
        if val:
            result["value"] = val
        dialog.destroy()

    save_btn = tk.Button(dialog, text="Save", relief="raised",
                         command=on_save, font=("Times", 20))

    # --- grid layout ---
    dialog.columnconfigure(0, minsize=205)
    title_frame.grid(row=0, column=0, sticky="NSEW")
    title_lbl.pack()
    keypad_frame.grid(row=1, column=0, sticky="NSEW")
    save_btn.grid(row=2, column=0)

    # Block until the dialog is closed
    parent.wait_window(dialog)

    return result["value"]


# ---------------------------------------------------------------------------
# Simple message popup
# ---------------------------------------------------------------------------

def show_message(parent, line1, line2=""):
    """
    Display a centred, borderless message popup with an OK button.
    Blocks until the user presses OK.

    Parameters
    ----------
    parent : tk.Tk or tk.Toplevel
    line1  : str  – first line of message text
    line2  : str  – optional second line
    """
    popup = tk.Toplevel(parent)
    popup.resizable(False, False)
    popup.overrideredirect(True)
    popup.config(cursor="none")

    w, h = 470, 170
    ws = parent.winfo_screenwidth()
    hs = parent.winfo_screenheight()
    x  = (ws // 2) - (w // 2)
    y  = (hs // 2) - (h // 2)
    popup.geometry(f"{w}x{h}+{x}+{y}")
    popup.config(bg="gray65")

    lbl1 = tk.Label(popup, text=line1, bg="gray65", font=('Times', 20))
    lbl2 = tk.Label(popup, text=line2, bg="gray65", font=('Times', 20))
    btn  = tk.Button(popup, text="OK", font=('Times', 20),
                     command=popup.destroy)

    lbl1.pack()
    lbl2.pack()
    btn.pack()

    parent.update_idletasks()
    parent.wait_window(popup)
