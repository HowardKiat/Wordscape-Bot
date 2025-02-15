#!/usr/bin/env python3

import os
import time
from collections import Counter
import datetime

import cv2 as cv
import numpy as np
import pyautogui
import pytesseract
from PIL import Image
from typing import Tuple, List, Union

# macOS: set `y_offset' to 45 to compensate for top-menu-bar and window-title-bar
y_offset = 0

# macOS: set `scale_factor' to 2 for mac-with-retina-display
scale_factor = 1

# adjust as necessary
config = {
    "window_max_size": 768,
    "window_height": 768,
    "screenshot_region": (0, 0, 353, 768 + y_offset),
    "circle_center": (176, 640 + y_offset),
    "shuffle_button": (32, 520 + y_offset),
    "close_piggybank": (285, 210 + y_offset),
    "circle_radius": 109,
    "rearranged_box_size": 64,
    "rearranged_padding": 8,
    "forbid_three_circle": (44, 44 + 22, 736 + y_offset, 736 + 22 + y_offset),
    "letter_contour_dim": (30, 39, 6, 50),
}

def upscale_t(t: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    return tuple(map(lambda f: f * scale_factor, t))

def downscale_t(t: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    return tuple(map(lambda f: f // scale_factor, t))

def scale_i(i: int) -> int:
    return i * scale_factor

def circle_contour() -> np.ndarray:
    r = scale_i(11)
    img = np.zeros((r * 4, r * 4, 1), np.uint8)
    img = cv.circle(img, (r * 2, r * 2), r, 255, -1)
    contours, _ = cv.findContours(img, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    return contours[0]

def largest_contour(image: np.ndarray) -> Union[np.ndarray, None]:
    contours, _ = cv.findContours(image, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    return max(contours, key=lambda cnt: cv.contourArea(cnt))

def is_forbid_three(img: Image, compare: np.ndarray) -> bool:
    img = cv.cvtColor(np.array(img), cv.COLOR_RGB2GRAY)
    otsu = cv.threshold(img, 127, 255, cv.THRESH_OTSU)[1]
    x0, x1, y0, y1 = upscale_t(config["forbid_three_circle"])
    sub_image = otsu[y0:y1, x0:x1]
    largest = largest_contour(sub_image)
    if largest is None:
        return False
    score = cv.matchShapes(largest, compare, cv.CONTOURS_MATCH_I1, 0.0)
    return score < 0.06

def detect_letters(img: Image) -> Tuple[bool, List[Tuple[str, Tuple[int, int]]]]:
    img = cv.cvtColor(np.array(img), cv.COLOR_RGB2GRAY)
    otsu = cv.threshold(img, 127, 255, cv.THRESH_OTSU)[1]

    mask = np.zeros(otsu.shape, np.uint8)
    center = upscale_t(config["circle_center"])
    radius = scale_i(config["circle_radius"])
    cv.circle(mask, center, radius, 1, -1)
    otsu = cv.bitwise_and(otsu, otsu, mask=mask)

    (px, py), size = center, scale_i(8)
    sample = otsu[py - size: py + size, px - size: px + size]
    if np.count_nonzero(sample) > sample.size // 2:
        otsu = cv.bitwise_not(otsu, otsu, mask=mask)

    all_contours, _ = cv.findContours(otsu, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    min_h, max_h, min_w, max_w = upscale_t(config["letter_contour_dim"])
    contours = [cnt for cnt in all_contours if min_h <= cv.boundingRect(cnt)[3] <= max_h and min_w <= cv.boundingRect(cnt)[2] <= max_w]

    if len(contours) not in (6, 7):
        return False, []

    box_size = scale_i(config["rearranged_box_size"])
    padding = scale_i(config["rearranged_padding"])
    rearranged = np.zeros((box_size, 8 * box_size), np.uint8)
    max_y, py, px = 0, padding, padding

    positions = []
    for cnt in contours:
        cx, cy, w, h = cv.boundingRect(cnt)
        positions.append((cx + (w // 2), cy + 2))
        rearranged[py: py + h, px: px + w] = otsu[cy: cy + h, cx: cx + w]
        max_y = max(max_y, py + h)
        px += w + padding

    rearranged = cv.bitwise_not(rearranged, rearranged)[: max_y + padding, :px]

    tes = pytesseract.image_to_string(rearranged, config="--psm 13")
    letters = [c for c in tes if c.isupper()]
    if len(letters) != len(positions):
        return False, []
    return True, list(zip(letters, positions))

def scrcpy():
    cmd = (
        "if pgrep -x scrcpy >/dev/null ;"
        "then echo 'scrcpy already running' ;"
        "else "
        "adb shell 'monkey -p com.peoplefun.wordcross 1' && "
        "nohup scrcpy --stay-awake --turn-screen-off --always-on-top --window-borderless "
        f"--window-x 0 --window-y 0 --max-size {config['window_max_size']} "
        f"--window-height {config['window_height']} >/dev/null 2>&1 &"
        "fi"
    )
    os.system(cmd)

def load_words() -> set:
    with open("words.txt") as fp:
        return set(fp.read().split())

def match_words(word_list: set, letters: List[Tuple[str, Tuple[int, int]]]) -> List[str]:
    ctr = Counter([k[0].lower() for k in letters])
    return [w for w in word_list if not Counter(w) - ctr]

def build_moves(word: str, positions: List[Tuple[str, Tuple[int, int]]]) -> List[Tuple[int, int]]:
    res = []
    for k in word.upper():
        for letter, (px, py) in positions:
            if letter == k and (px, py) not in res:
                res.append((px, py))
                break
    return res

def click(xy_t: Tuple[int, int]):
    pyautogui.click(*xy_t)

def main():
    scrcpy()
    all_words = load_words()
    circle = circle_contour()
    prev_letters = ""

    while True:
        click(config["circle_center"])
        time.sleep(0.7)

        region = upscale_t(config["screenshot_region"])
        capture = pyautogui.screenshot(region=region).convert("RGB")

        success, detected = detect_letters(capture)
        if not success:
            click(config["shuffle_button"])
            click(config["close_piggybank"])
            continue

        letters = "".join([k[0] for k in detected])
        if letters == prev_letters:
            click(config["shuffle_button"])
            continue
        prev_letters = letters

        matches = match_words(all_words, detected)
        if is_forbid_three(capture, circle):
            matches = [w for w in matches if len(w) > 3]

        matches.sort(key=lambda k: (len(k), k))

        for matched_word in matches:
            moves = build_moves(matched_word, detected)
            for index, (x, y) in enumerate(moves):
                x, y = downscale_t((x, y))
                if index == 0:
                    pyautogui.mouseDown(x, y, pyautogui.LEFT)
                elif index == len(moves) - 1:
                    pyautogui.mouseUp(x, y, pyautogui.LEFT)
                else:
                    pyautogui.moveTo(x, y, 0.1)
            time.sleep(0.1)
        time.sleep(12)

if __name__ == "__main__":
    main()
