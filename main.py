# main.py
import tkinter as tk
import os
from gui import GoofishGUI

if __name__ == "__main__":
    root = tk.Tk()
    app = GoofishGUI(root)

    def on_close():

        try:
            root.destroy()
        except:
            pass
        os._exit(0)

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()