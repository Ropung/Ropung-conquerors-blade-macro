"""Import input libraries without registering hooks or sending input."""
import cv2
import numpy
import mss
import pyautogui
import pydirectinput
import keyboard
from window_only import main

if __name__ == "__main__":
    raise SystemExit(main("03 - Window + recognition + input libraries"))
