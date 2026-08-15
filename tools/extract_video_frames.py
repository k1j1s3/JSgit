#!/usr/bin/env python3
"""Extract evenly spaced video frames into compact contact sheets."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
from PIL import Image, ImageDraw


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--end", type=float)
    parser.add_argument("--individual", action="store_true")
    args = parser.parse_args()

    capture = cv2.VideoCapture(str(args.video))
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frames / fps
    thumbs: list[Image.Image] = []
    timestamp = max(0.0, args.start)
    end = duration if args.end is None else min(duration, args.end)
    while timestamp <= end:
        capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        ok, frame = capture.read()
        if not ok:
            break
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(frame)
        if args.individual:
            args.output.mkdir(parents=True, exist_ok=True)
            image.save(args.output / f"frame-{timestamp:07.2f}.jpg", quality=95)
        image.thumbnail((320, 180))
        tile = Image.new("RGB", (320, 200), "black")
        tile.paste(image, (0, 0))
        ImageDraw.Draw(tile).text((6, 183), f"{timestamp:06.1f}s", fill="white")
        thumbs.append(tile)
        timestamp += args.interval
    capture.release()

    args.output.mkdir(parents=True, exist_ok=True)
    for page, offset in enumerate(range(0, len(thumbs), 20), start=1):
        sheet = Image.new("RGB", (1280, 1000), "black")
        for index, tile in enumerate(thumbs[offset : offset + 20]):
            sheet.paste(tile, ((index % 4) * 320, (index // 4) * 200))
        sheet.save(args.output / f"contact-{page:02}.jpg", quality=90)
    print(f"duration={duration:.2f}s samples={len(thumbs)} pages={(len(thumbs) + 19) // 20}")


if __name__ == "__main__":
    main()
