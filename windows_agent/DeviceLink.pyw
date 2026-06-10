#!/usr/bin/env pythonw
"""
DeviceLink Standalone Launcher (No Console Window)
"""
import sys
import os

# Ensure the directory of this script is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui import DeviceLinkApp

if __name__ == "__main__":
    app = DeviceLinkApp()
    app.mainloop()
