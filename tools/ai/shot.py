"""PGD / Illustrator: capture one window to PNG with PrintWindow (works when the window is behind others).
    python shot.py HWND out.png"""
import ctypes, sys
import win32gui, win32ui
from PIL import Image


def shot(h, out):
    l, t, r, b = win32gui.GetWindowRect(h)
    w, hh = r - l, b - t
    hdc = win32gui.GetWindowDC(h)
    src = win32ui.CreateDCFromHandle(hdc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, w, hh)
    mem.SelectObject(bmp)
    ctypes.windll.user32.PrintWindow(h, mem.GetSafeHdc(), 2)
    info = bmp.GetInfo()
    Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1).save(out)
    win32gui.DeleteObject(bmp.GetHandle())
    mem.DeleteDC()
    src.DeleteDC()
    win32gui.ReleaseDC(h, hdc)


if __name__ == "__main__":
    shot(int(sys.argv[1]), sys.argv[2])
