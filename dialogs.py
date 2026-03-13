# dialogs.py
#
# Uses in-window overlay frames instead of Toplevel popups.
# This avoids all Wayland/XWayland compositor issues entirely.
# No new windows are created — overlays are placed directly on the root window.
#
# Usage:
#   from dialogs import OverlayManager
#   # In App.__init__:
#   self.overlay = OverlayManager(self.root)
#   # To show number pad:
#   val = self.overlay.number_pad("Set Volume")
#   # To show message:
#   self.overlay.message("Error", "Please enter a number")

import tkinter as tk
from tkinter import ttk


class OverlayManager:
    """
    Manages modal overlays drawn directly on the root window.
    No Toplevel windows — no Wayland compositor involvement.
    """

    def __init__(self, root):
        self.root = root

    def number_pad(self, title="Enter Value"):
        """
        Show a number pad overlay on the root window.
        Blocks (via manual event loop) until Save is pressed.
        Returns the entered string or None.
        """
        result = {"value": None, "done": False}

        # Blocker frame covers entire window to catch stray touches
        blocker = tk.Frame(self.root, bg="gray30")
        blocker.place(x=0, y=0, relwidth=1, relheight=1)

        # Main dialog frame centred on window
        frame = tk.Frame(self.root, bg="gray95", bd=4, relief="ridge")
        frame.place(relx=0.5, rely=0.5, anchor="center", width=220, height=410)

        tk.Label(frame, text=title, bg="gray95",
                 font=("Times", 20)).grid(row=0, column=0, columnspan=3,
                                          pady=(8, 4), padx=8, sticky="EW")
        ttk.Separator(frame, orient="horizontal").grid(
            row=1, column=0, columnspan=3, sticky="EW", padx=4)

        entry_var = tk.StringVar()
        entry = tk.Entry(frame, textvariable=entry_var,
                         font=("Times", 18), justify="right")
        entry.grid(row=2, column=0, columnspan=3, padx=8, pady=4,
                   ipady=4, sticky="EW")

        def on_key(v):
            if v == '<':
                entry_var.set(entry_var.get()[:-1])
            else:
                entry_var.set(entry_var.get() + v)

        keys = [
            ['1', '2', '3'],
            ['4', '5', '6'],
            ['7', '8', '9'],
            ['.', '0', '<'],
        ]
        for r, row in enumerate(keys, start=3):
            for c, key in enumerate(row):
                tk.Button(frame, text=key, font=("Times", 22),
                          command=lambda v=key: on_key(v)
                          ).grid(row=r, column=c, ipadx=10, ipady=8,
                                 padx=2, pady=2, sticky="NSEW")

        def on_save():
            val = entry_var.get().strip()
            if val:
                result["value"] = val
            result["done"] = True

        tk.Button(frame, text="Save", font=("Times", 20), bg="lightgreen",
                  command=on_save).grid(row=7, column=0, columnspan=3,
                                        pady=6, padx=8, sticky="EW")

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)

        # Raise overlay above everything
        blocker.lift()
        frame.lift()
        self.root.update()

        # Manual event loop — no wait_window, no grab_set
        while not result["done"]:
            try:
                self.root.update()
            except tk.TclError:
                break

        frame.destroy()
        blocker.destroy()
        self.root.update()
        return result["value"]

    def message(self, line1, line2=""):
        """
        Show a message overlay with an OK button.
        Blocks until OK is pressed.
        """
        result = {"done": False}

        blocker = tk.Frame(self.root, bg="gray30")
        blocker.place(x=0, y=0, relwidth=1, relheight=1)

        frame = tk.Frame(self.root, bg="gray65", bd=4, relief="ridge")
        frame.place(relx=0.5, rely=0.5, anchor="center", width=480, height=180)

        tk.Label(frame, text=line1, bg="gray65",
                 font=("Times", 20)).pack(pady=(20, 4))
        if line2:
            tk.Label(frame, text=line2, bg="gray65",
                     font=("Times", 18)).pack()
        tk.Button(frame, text="OK", font=("Times", 20), width=8,
                  command=lambda: result.update({"done": True})
                  ).pack(pady=10)

        blocker.lift()
        frame.lift()
        self.root.update()

        while not result["done"]:
            try:
                self.root.update()
            except tk.TclError:
                break

        frame.destroy()
        blocker.destroy()
        self.root.update()


# ---------------------------------------------------------------------------
# Legacy shim — keeps old call sites working during transition
# These are no longer used but kept so nothing breaks if called directly
# ---------------------------------------------------------------------------
def number_pad_dialog(parent, title="Enter Value"):
    mgr = OverlayManager(parent)
    return mgr.number_pad(title)

def show_message(parent, line1, line2=""):
    mgr = OverlayManager(parent)
    mgr.message(line1, line2)
