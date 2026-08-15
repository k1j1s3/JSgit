#!/usr/bin/env python3
"""Screen-driven safety automation for the local Lineage M test server.

The tool intentionally uses only ADB screenshots and taps.  It does not inject
code into the game process or inspect game memory.  A PvP threat is declared
only when a meaningful HP drop and a nearby cyan player-name signal occur in
the same short time window.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "auto_hunt.json"


@dataclass(frozen=True)
class FrameState:
    timestamp: float
    hp_ratio: float
    cyan_pixels: int
    safe_zone_pixels: int


def run_adb(adb: str, device: str, *args: str, binary: bool = False):
    command = [adb, "-s", device, *args]
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=not binary,
        timeout=20,
    ).stdout


def screenshot(adb: str, device: str) -> Image.Image:
    data = run_adb(adb, device, "exec-out", "screencap", "-p", binary=True)
    return Image.open(io.BytesIO(data)).convert("RGB")


def crop_pixels(image: Image.Image, rect: list[int]):
    x1, y1, x2, y2 = rect
    region = image.crop((x1, y1, x2, y2))
    pixels = region.load()
    width, height = region.size
    return (pixels[x, y] for y in range(height) for x in range(width))


def measure_hp(image: Image.Image, rect: list[int]) -> float:
    """Estimate filled red HP-bar width, tolerating text drawn over the bar."""
    region = image.crop(tuple(rect))
    width, height = region.size
    occupied = []
    for x in range(width):
        red = 0
        for y in range(height):
            r, g, b = region.getpixel((x, y))
            if r >= 135 and r >= g * 1.45 and r >= b * 1.35:
                red += 1
        occupied.append(red >= max(1, height // 5))
    # Small gaps are normally caused by the white HP text.
    last = -1
    gap = 0
    for x, filled in enumerate(occupied):
        if filled:
            last = x
            gap = 0
        elif last >= 0:
            gap += 1
            if gap > 18:
                break
    return max(0.0, min(1.0, (last + 1) / max(1, width)))


def count_cyan(image: Image.Image, rect: list[int]) -> int:
    count = 0
    for r, g, b in crop_pixels(image, rect):
        if b >= 125 and g >= 80 and b >= r * 1.25 and (b - r) >= 45:
            count += 1
    return count


def count_safe_zone_color(image: Image.Image, rect: list[int]) -> int:
    # The Safety Zone label is cyan/blue in the verified 1280x720 UI.
    return count_cyan(image, rect)


def tap(adb: str, device: str, x: int, y: int):
    run_adb(adb, device, "shell", "input", "tap", str(x), str(y))


def execute_actions(adb: str, device: str, actions: list[dict], logger):
    for action in actions:
        kind = action.get("type")
        if kind == "tap":
            x, y = action["point"]
            logger.info("tap (%s, %s): %s", x, y, action.get("label", ""))
            tap(adb, device, x, y)
        elif kind == "wait":
            seconds = float(action["seconds"])
            logger.info("wait %.1fs: %s", seconds, action.get("label", ""))
            time.sleep(seconds)
        else:
            raise ValueError(f"unknown action type: {kind!r}")


def save_evidence(image: Image.Image, output: Path, device: str, label: str):
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = output / f"{stamp}-{device.replace(':', '_')}-{label}.png"
    image.save(path)
    return path


def detect_threat(history: deque[FrameState], cfg: dict) -> tuple[bool, str]:
    if len(history) < 2:
        return False, "warming-up"
    now = history[-1]
    window = float(cfg["detection"]["hp_drop_window_seconds"])
    prior = [sample for sample in history if now.timestamp - sample.timestamp <= window]
    highest = max(sample.hp_ratio for sample in prior)
    hp_drop = highest - now.hp_ratio
    cyan = now.cyan_pixels
    enough_drop = hp_drop >= float(cfg["detection"]["minimum_hp_drop_ratio"])
    player_nearby = cyan >= int(cfg["detection"]["minimum_cyan_pixels"])
    not_safe = now.safe_zone_pixels < int(cfg["detection"]["safe_zone_cyan_pixels"])
    reason = (
        f"hp={now.hp_ratio:.3f} drop={hp_drop:.3f} "
        f"cyan={cyan} safe={now.safe_zone_pixels}"
    )
    return enough_drop and player_nearby and not_safe, reason


def device_loop(global_cfg: dict, device_cfg: dict, once: bool = False):
    adb = global_cfg["adb_path"]
    device = device_cfg["device"]
    interval = float(global_cfg["poll_interval_seconds"])
    output = ROOT / global_cfg["evidence_directory"]
    history: deque[FrameState] = deque(maxlen=30)
    cooldown_until = 0.0
    logger = logging.getLogger(device)

    while True:
        image = screenshot(adb, device)
        now = time.monotonic()
        state = FrameState(
            timestamp=now,
            hp_ratio=measure_hp(image, device_cfg["regions"]["hp_bar"]),
            cyan_pixels=count_cyan(image, device_cfg["regions"]["world_player_names"]),
            safe_zone_pixels=count_safe_zone_color(
                image, device_cfg["regions"]["zone_label"]
            ),
        )
        history.append(state)
        threat, reason = detect_threat(history, global_cfg)
        logger.info("state %s threat=%s", reason, threat)

        if threat and now >= cooldown_until:
            evidence = save_evidence(image, output, device, "threat")
            logger.warning("PvP threat detected: %s evidence=%s", reason, evidence)
            if global_cfg["dry_run"]:
                logger.warning("dry_run=true: return/travel actions were not sent")
            else:
                execute_actions(adb, device, device_cfg["return_actions"], logger)
                route = device_cfg["hunting_routes"][device_cfg.get("next_route", 0)]
                execute_actions(adb, device, route["actions"], logger)
                device_cfg["next_route"] = (
                    int(device_cfg.get("next_route", 0)) + 1
                ) % len(device_cfg["hunting_routes"])
            cooldown_until = now + float(global_cfg["detection"]["cooldown_seconds"])
            history.clear()

        if once:
            return state
        time.sleep(interval)


def validate(config: dict):
    if not Path(config["adb_path"]).exists():
        raise FileNotFoundError(f"ADB not found: {config['adb_path']}")
    if not config.get("devices"):
        raise ValueError("at least one device must be configured")
    for device in config["devices"]:
        for name in ("hp_bar", "world_player_names", "zone_label"):
            rect = device["regions"][name]
            if len(rect) != 4 or rect[2] <= rect[0] or rect[3] <= rect[1]:
                raise ValueError(f"invalid {name} region for {device['device']}: {rect}")
        if not config["dry_run"] and not device.get("hunting_routes"):
            raise ValueError(f"no hunting routes configured for {device['device']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--device", help="monitor only this ADB serial")
    parser.add_argument("--once", action="store_true", help="measure one frame and exit")
    parser.add_argument("--log-file", type=Path, help="also write logs to this file")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    validate(config)
    handlers = [logging.StreamHandler()]
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=handlers,
    )
    devices = config["devices"]
    if args.device:
        devices = [item for item in devices if item["device"] == args.device]
        if not devices:
            raise SystemExit(f"device is not configured: {args.device}")

    # One-device mode is intentional for actionable automation. Run one process
    # per player so a stalled emulator cannot delay the other player's escape.
    if len(devices) > 1 and not args.once:
        raise SystemExit("Select one device with --device; run one process per player.")
    for device in devices:
        state = device_loop(config, device, once=args.once)
        if args.once:
            print(
                f"{device['device']} hp={state.hp_ratio:.3f} "
                f"cyan={state.cyan_pixels} safe={state.safe_zone_pixels}"
            )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
