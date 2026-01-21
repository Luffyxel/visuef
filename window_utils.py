from typing import List, Tuple

import pygetwindow as gw
import win32gui


def list_windows() -> List[Tuple[str, int]]:
    """Return (title, hwnd) for visible windows with a valid rectangle."""
    results: List[Tuple[str, int]] = []
    seen = set()
    for win in gw.getAllWindows():
        title = win.title.strip()
        hwnd = getattr(win, "_hWnd", None)
        if not title or hwnd is None:
            continue
        try:
            if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                continue
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            if right - left <= 0 or bottom - top <= 0:
                continue
        except Exception:
            continue
        if hwnd in seen:
            continue
        seen.add(hwnd)
        results.append((title, hwnd))
    return results
