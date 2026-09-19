#!/usr/bin/env python3
"""
veltrix_gui.py - launcher for the Veltrix 1.0 chess GUI.

Usage:  python veltrix_gui.py        (or double-click; on Windows the file
        association opens pythonw.exe so no console window appears)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from app import main          # noqa: E402

if __name__ == "__main__":
    main()
