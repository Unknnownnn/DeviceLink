#!/usr/bin/env pythonw
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui import DeviceLinkApp

if __name__ == "__main__":
    app = DeviceLinkApp()
    app.mainloop()
