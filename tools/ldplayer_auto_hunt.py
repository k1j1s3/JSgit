#!/usr/bin/env python3
"""Screen-driven safety automation for the local Lineage M test server.

The tool intentionally uses only ADB screenshots and taps.  It does not inject
code into the game process or inspect game memory.  A PvP threat is declared
only when a meaningful HP drop and a nearby cyan player-name signal occur in
the same short time window.
"""

from __future__ import annotations

import argparse
import copy
import io
import json
import logging
import random
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "auto_hunt.json"


@dataclass(frozen=True)
class FrameState:
    timestamp: float
    hp_ratio: float
    cyan_pixels: int
    hostile_magenta_pixels: int
    pvp_red_pixels: int
    safe_zone_pixels: int


@dataclass
class WorldBossRuntime:
    state: str = "idle"
    state_since: float = 0.0
    last_action: float = 0.0
    loot_frames: int = 0
    suppress_until: float = 0.0
    icon_frames: int = 0
    completed_slot: str = ""
    loot_empty_frames: int = 0
    motion_index: int = 0


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
    """Estimate filled HP width for the normal red or status-effect green bar."""
    region = image.crop(tuple(rect))
    width, height = region.size
    occupied = []
    for x in range(width):
        filled_pixels = 0
        for y in range(height):
            r, g, b = region.getpixel((x, y))
            red_hp = r >= 135 and r >= g * 1.45 and r >= b * 1.35
            green_hp = g >= 105 and g >= r * 1.25 and g >= b * 1.15
            if red_hp or green_hp:
                filled_pixels += 1
        occupied.append(filled_pixels >= max(1, height // 5))
    # Ignore isolated colored UI pixels before/after the bar.  The actual bar
    # is the densest horizontal cluster; short holes come from HP text.
    filled_x = [x for x, filled in enumerate(occupied) if filled]
    if not filled_x:
        return 0.0
    clusters = []
    cluster = [filled_x[0]]
    for x in filled_x[1:]:
        if x - cluster[-1] - 1 <= 4:
            cluster.append(x)
        else:
            clusters.append(cluster)
            cluster = [x]
    clusters.append(cluster)
    bar = max(clusters, key=lambda values: (len(values), values[-1] - values[0]))
    return max(0.0, min(1.0, (bar[-1] + 1) / max(1, width)))


def count_cyan(image: Image.Image, rect: list[int]) -> int:
    count = 0
    for r, g, b in crop_pixels(image, rect):
        if b >= 125 and g >= 80 and b >= r * 1.25 and (b - r) >= 45:
            count += 1
    return count


def count_hostile_magenta(image: Image.Image, rect: list[int]) -> int:
    """Count the pink/purple hostile-player name and targeting treatment."""
    count = 0
    for r, g, b in crop_pixels(image, rect):
        if r >= 130 and b >= 130 and g < min(r, b) * 0.82 and abs(r - b) < 100:
            count += 1
    return count


def count_pvp_red(image: Image.Image, rect: list[int]) -> int:
    count = 0
    for r, g, b in crop_pixels(image, rect):
        if r >= 150 and g <= 95 and b <= 95 and r >= g * 1.8 and r >= b * 1.8:
            count += 1
    return count


def count_safe_zone_color(image: Image.Image, rect: list[int]) -> int:
    # The Safety Zone label is cyan/blue in the verified 1280x720 UI.
    return count_cyan(image, rect)


def count_world_boss_red(image: Image.Image, rect: list[int]) -> int:
    count = 0
    for r, g, b in crop_pixels(image, rect):
        if r >= 150 and r >= g * 1.5 and r >= b * 1.4:
            count += 1
    return count


def count_gold(image: Image.Image, rect: list[int]) -> int:
    count = 0
    for r, g, b in crop_pixels(image, rect):
        if r >= 150 and g >= 90 and b < 110 and r >= g * 1.05:
            count += 1
    return count


def world_boss_icon_visible(image: Image.Image, cfg: dict) -> bool:
    """Require the four red diamond quadrants and its gold caption/countdown."""
    quadrants = cfg["icon_quadrants"]
    minimum_quadrant = int(cfg["minimum_icon_quadrant_red_pixels"])
    diamond = all(count_world_boss_red(image, rect) >= minimum_quadrant for rect in quadrants)
    caption = count_gold(image, cfg["icon_caption_region"]) >= int(
        cfg["minimum_icon_caption_gold_pixels"]
    )
    return diamond and caption


def count_loot_text(image: Image.Image, rect: list[int]) -> int:
    """Count bright, low-saturation pixels from the dense ground-item labels."""
    count = 0
    for r, g, b in crop_pixels(image, rect):
        if min(r, g, b) >= 175 and max(r, g, b) - min(r, g, b) < 55:
            count += 1
    return count


def find_priority_loot_target(image: Image.Image, rect: list[int]) -> tuple[str, tuple[int, int]] | None:
    """Find the densest legendary, hero, then rare colored label area."""
    x1, y1, x2, y2 = rect
    rules = (
        ("legendary-purple", lambda r, g, b: r >= 140 and b >= 150 and g <= 115),
        ("hero-red", lambda r, g, b: r >= 180 and g <= 130 and b <= 125 and r >= g * 1.35),
        ("rare-blue", lambda r, g, b: b >= 150 and g >= 80 and r <= 125 and b >= r * 1.3),
    )
    # Text crosses several small bins. Picking the densest bin is more stable
    # than averaging all same-colored combat effects and player names.
    bin_size = 32
    for label, matches in rules:
        bins: dict[tuple[int, int], list[int]] = {}
        for y in range(y1, y2, 2):
            for x in range(x1, x2, 2):
                r, g, b = image.getpixel((x, y))
                if matches(r, g, b):
                    key = ((x - x1) // bin_size, (y - y1) // bin_size)
                    bucket = bins.setdefault(key, [0, 0, 0])
                    bucket[0] += 1
                    bucket[1] += x
                    bucket[2] += y
        if bins:
            count, sx, sy = max(bins.values(), key=lambda item: item[0])
            if count >= 5:
                return label, (sx // count, sy // count)
    return None


def tap(adb: str, device: str, x: int, y: int):
    run_adb(adb, device, "shell", "input", "tap", str(x), str(y))


def swipe(adb: str, device: str, start: list[int], end: list[int], duration_ms: int):
    run_adb(
        adb,
        device,
        "shell",
        "input",
        "swipe",
        str(start[0]),
        str(start[1]),
        str(end[0]),
        str(end[1]),
        str(duration_ms),
    )


def is_auto_active(image: Image.Image, rect: list[int], minimum_orange_pixels: int) -> bool:
    """Detect the orange AUTO ring shown while automatic combat is active."""
    orange_pixels = 0
    for r, g, b in crop_pixels(image, rect):
        if r >= 150 and 60 <= g <= 180 and b < 80 and r >= g * 1.25:
            orange_pixels += 1
    return orange_pixels >= minimum_orange_pixels


def is_close_overlay_open(image: Image.Image, rect: list[int], minimum_red_pixels: int = 80) -> bool:
    red_pixels = sum(
        1 for r, g, b in crop_pixels(image, rect)
        if r >= 120 and r >= g * 1.45 and r >= b * 1.35
    )
    return red_pixels >= minimum_red_pixels


def is_main_menu_open(image: Image.Image, rect: list[int], minimum_panel_pixels: int = 10000) -> bool:
    """Detect the large navy main-menu panel, ignoring the red notification dot."""
    panel_pixels = sum(
        1 for r, g, b in crop_pixels(image, rect)
        if b >= 25 and b >= r * 1.25 and b >= g * 1.12
    )
    return panel_pixels >= minimum_panel_pixels


def is_death_panel_visible(image: Image.Image, cfg: dict) -> bool:
    """Recognize the brown death modal together with its blue restart button."""
    button = cfg.get("death_restart_button_region", [555, 547, 725, 591])
    panel = cfg.get("death_panel_region", [390, 65, 890, 605])
    blue = sum(
        1 for r, g, b in crop_pixels(image, button)
        if b >= 55 and b >= r * 1.15 and b >= g * 1.05
    )
    brown = sum(
        1 for r, g, b in crop_pixels(image, panel)
        if r >= 35 and r >= g * 1.15 and g >= b * 1.05
    )
    return (
        blue >= int(cfg.get("minimum_death_button_blue_pixels", 4000))
        and brown >= int(cfg.get("minimum_death_panel_brown_pixels", 100000))
    )


def reference_similarity(image: Image.Image, reference: Image.Image, regions: list[list[int]]) -> float:
    scores = []
    for rect in regions:
        current = image.crop(tuple(rect)).convert("RGB")
        expected = reference.crop(tuple(rect)).convert("RGB")
        difference = ImageChops.difference(current, expected)
        mean = sum(ImageStat.Stat(difference).mean) / (3 * 255)
        scores.append(1.0 - mean)
    return sum(scores) / max(1, len(scores))


def execute_actions(adb: str, device: str, actions: list[dict], logger):
    for action in actions:
        kind = action.get("type")
        if kind == "tap":
            x, y = action["point"]
            logger.info("tap (%s, %s): %s", x, y, action.get("label", ""))
            tap(adb, device, x, y)
        elif kind == "swipe":
            start = action["start"]
            end = action["end"]
            duration_ms = int(action.get("duration_ms", 450))
            logger.info(
                "swipe %s -> %s (%sms): %s",
                start,
                end,
                duration_ms,
                action.get("label", ""),
            )
            swipe(adb, device, start, end, duration_ms)
        elif kind == "ensure_auto":
            rect = action.get("region", [960, 500, 1040, 590])
            minimum = int(action.get("minimum_orange_pixels", 500))
            # The orange AUTO ring can be absent for a frame while the field HUD
            # is still settling after teleport.  Treat any positive sample as
            # active so an already-running AUTO mode is never toggled off.
            sample_count = int(action.get("sample_count", 5))
            sample_interval = float(action.get("sample_interval_seconds", 0.35))
            samples = []
            for index in range(sample_count):
                samples.append(is_auto_active(screenshot(adb, device), rect, minimum))
                if samples[-1]:
                    break
                if index + 1 < sample_count:
                    time.sleep(sample_interval)
            active = any(samples)
            logger.info("AUTO state active=%s: %s", active, action.get("label", ""))
            if not active:
                x, y = action["point"]
                logger.info("tap (%s, %s): enable AUTO combat", x, y)
                tap(adb, device, x, y)
        elif kind == "ensure_auto_off":
            rect = action.get("region", [960, 500, 1040, 590])
            minimum = int(action.get("minimum_orange_pixels", 500))
            sample_count = int(action.get("sample_count", 1))
            sample_interval = float(action.get("sample_interval_seconds", 0.2))
            active = False
            for index in range(sample_count):
                active = is_auto_active(screenshot(adb, device), rect, minimum)
                if active:
                    break
                if index + 1 < sample_count:
                    time.sleep(sample_interval)
            logger.info("AUTO state active=%s: %s", active, action.get("label", ""))
            if active:
                x, y = action["point"]
                logger.info("tap (%s, %s): disable AUTO during town chores", x, y)
                tap(adb, device, x, y)
        elif kind == "close_overlay_if_open":
            rect = action.get("region", [1200, 5, 1270, 75])
            open_ = is_close_overlay_open(screenshot(adb, device), rect)
            logger.info("close overlay open=%s: %s", open_, action.get("label", ""))
            if open_:
                x, y = action.get("point", [1235, 43])
                tap(adb, device, x, y)
        elif kind == "close_main_menu_if_open":
            rect = action.get("region", [900, 80, 1270, 680])
            minimum = int(action.get("minimum_panel_pixels", 10000))
            open_ = is_main_menu_open(screenshot(adb, device), rect, minimum)
            logger.info("main menu open=%s: %s", open_, action.get("label", ""))
            if open_:
                x, y = action.get("point", [1235, 43])
                tap(adb, device, x, y)
                wait_after = float(action.get("wait_after_seconds", 0.0))
                if wait_after > 0:
                    logger.info("wait %.2fs for main menu close animation", wait_after)
                    time.sleep(wait_after)
        elif kind == "wait_for_gameplay":
            timeout = float(action.get("timeout_seconds", 3.0))
            deadline = time.monotonic() + timeout
            time.sleep(float(action.get("initial_delay_seconds", 0.5)))
            ready = False
            while time.monotonic() < deadline:
                frame = screenshot(adb, device)
                hp = measure_hp(frame, action.get("hp_region", [88, 41, 319, 58]))
                overlay = is_close_overlay_open(frame, action.get("close_region", [1200, 5, 1270, 75]))
                if hp > 0.05 and not overlay:
                    ready = True
                    break
                time.sleep(0.15)
            logger.info("gameplay ready=%s within %.1fs: %s", ready, timeout, action.get("label", ""))
        elif kind == "verify_reference":
            reference_path = ROOT / action["reference"]
            if not reference_path.exists():
                logger.error("verification reference missing: %s", reference_path)
                return False
            current = screenshot(adb, device)
            reference = Image.open(reference_path).convert("RGB")
            score = reference_similarity(current, reference, action["regions"])
            minimum = float(action.get("minimum_similarity", 0.90))
            logger.info("reference verification score=%.3f minimum=%.3f: %s", score, minimum, action.get("label", ""))
            if score < minimum:
                logger.error("unexpected UI; aborting remaining actions")
                return False
        elif kind == "wait":
            seconds = float(action["seconds"])
            logger.info("wait %.1fs: %s", seconds, action.get("label", ""))
            time.sleep(seconds)
        else:
            raise ValueError(f"unknown action type: {kind!r}")
    return True


def save_evidence(image: Image.Image, output: Path, device: str, label: str):
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = output / f"{stamp}-{device.replace(':', '_')}-{label}.png"
    image.save(path)
    return path


def detect_threat(
    history: deque[FrameState], cfg: dict, emergency_in_safe_zone: bool = False,
    emergency_only: bool = False,
) -> tuple[bool, str]:
    now = history[-1]
    not_safe = now.safe_zone_pixels < int(cfg["detection"]["safe_zone_cyan_pixels"])
    critical_limit = float(cfg["detection"].get("critical_hp_ratio", 0.15))
    critical_hp = 0.0 < now.hp_ratio <= critical_limit
    emergency_limit = float(cfg["detection"].get("emergency_hp_ratio", 0.25))
    emergency_frames = int(cfg["detection"].get("emergency_confirm_frames", 2))
    recent_emergency = list(history)[-emergency_frames:]
    emergency_hp = len(recent_emergency) == emergency_frames and all(
        0.0 < sample.hp_ratio <= emergency_limit for sample in recent_emergency
    )
    if (critical_hp or emergency_hp) and (not_safe or emergency_in_safe_zone):
        tier = "critical" if critical_hp else "confirmed-low"
        return True, f"{tier}-hp hp={now.hp_ratio:.3f} safe={now.safe_zone_pixels}"
    if emergency_only:
        return False, f"quest-mode hp={now.hp_ratio:.3f} safe={now.safe_zone_pixels}"
    if len(history) < 2:
        return False, "warming-up"
    window = float(cfg["detection"]["hp_drop_window_seconds"])
    prior = [sample for sample in history if now.timestamp - sample.timestamp <= window]
    highest = max(sample.hp_ratio for sample in prior)
    hp_drop = highest - now.hp_ratio
    rapid_drop_limit = float(cfg["detection"].get("rapid_drop_ratio", 1.0))
    rapid_drop_ceiling = float(cfg["detection"].get("rapid_drop_hp_ceiling", 0.0))
    rapid_drop = (
        0.0 < now.hp_ratio <= rapid_drop_ceiling
        and hp_drop >= rapid_drop_limit
    )
    if rapid_drop and not_safe:
        return True, (
            f"rapid-hp-drop hp={now.hp_ratio:.3f} drop={hp_drop:.3f} "
            f"safe={now.safe_zone_pixels}"
        )
    cyan = now.cyan_pixels
    hostile = now.hostile_magenta_pixels
    pvp_red = now.pvp_red_pixels
    enough_drop = hp_drop >= float(cfg["detection"]["minimum_hp_drop_ratio"])
    player_nearby = cyan >= int(cfg["detection"]["minimum_cyan_pixels"])
    hostile_visible = hostile >= int(
        cfg["detection"]["minimum_hostile_magenta_pixels"]
    )
    pvp_visible = pvp_red >= int(cfg["detection"]["minimum_pvp_red_pixels"])
    reason = (
        f"hp={now.hp_ratio:.3f} drop={hp_drop:.3f} "
        f"cyan={cyan} hostile={hostile} pvp_red={pvp_red} "
        f"safe={now.safe_zone_pixels}"
    )
    if not cfg["detection"].get("pvp_detection_enabled", True):
        return False, reason + " pvp-detection-disabled"
    strong_frames = int(cfg["detection"].get("strong_pvp_confirm_frames", 2))
    strong_threshold = int(cfg["detection"].get("strong_pvp_red_pixels", 2000))
    recent_pvp = list(history)[-strong_frames:]
    strong_pvp = len(recent_pvp) == strong_frames and all(
        sample.pvp_red_pixels >= strong_threshold for sample in recent_pvp
    )
    if strong_pvp and not_safe:
        return True, reason + " strong-pvp-confirmed"
    if not cfg["detection"].get("legacy_pvp_detection_enabled", False):
        return False, reason
    # Ordinary monster packs also produce cyan/magenta combat pixels.  A HP
    # drop is only treated as PvP when the dedicated PvP UI is visible too.
    hp_signal = enough_drop and player_nearby and hostile_visible and pvp_visible
    pvp_ui_signal = pvp_visible and hostile_visible and player_nearby
    return (hp_signal or pvp_ui_signal) and not_safe, reason


def world_boss_schedule_active(now: datetime, cfg: dict) -> bool:
    before = int(cfg.get("schedule_before_seconds", 90))
    after = int(cfg.get("schedule_after_seconds", 1200))
    for value in cfg.get("schedule", []):
        hour, minute = (int(part) for part in value.split(":"))
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if scheduled - timedelta(seconds=before) <= now <= scheduled + timedelta(seconds=after):
            return True
    return False


def world_boss_schedule_slot(now: datetime, cfg: dict) -> str:
    before = int(cfg.get("schedule_before_seconds", 90))
    after = int(cfg.get("schedule_after_seconds", 180))
    for value in cfg.get("schedule", []):
        hour, minute = (int(part) for part in value.split(":"))
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if scheduled - timedelta(seconds=before) <= now <= scheduled + timedelta(seconds=after):
            return scheduled.strftime("%Y-%m-%dT%H:%M")
    return ""


def world_boss_marker_path(device: str) -> Path:
    return ROOT / "data" / "auto-hunt" / f"world-boss-{device}.json"


def load_world_boss_marker(device: str) -> str:
    path = world_boss_marker_path(device)
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("slot", ""))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ""


def save_world_boss_marker(device: str, slot: str):
    path = world_boss_marker_path(device)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"slot": slot}), encoding="utf-8")


def hunting_route_marker_path(device: str) -> Path:
    return ROOT / "data" / "auto-hunt" / f"hunting-route-{device}.json"


def load_hunting_route_index(device: str, route_count: int) -> int:
    if route_count <= 0:
        return 0
    try:
        payload = json.loads(hunting_route_marker_path(device).read_text(encoding="utf-8"))
        return int(payload.get("next_index", 0)) % route_count
    except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return 0


def save_hunting_route_index(device: str, next_index: int):
    path = hunting_route_marker_path(device)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"next_index": next_index}), encoding="utf-8")


def burst_tap(adb: str, device: str, point: list[int], count: int, delay: float):
    for _ in range(count):
        tap(adb, device, point[0], point[1])
        time.sleep(delay)


def radar_select_first_target(adb: str, device: str, device_boss: dict, logger):
    """Refresh the in-game target radar and select its first row."""
    logger.info("radar refresh and select target row 1")
    tap(adb, device, *device_boss["radar_point"])
    time.sleep(float(device_boss.get("radar_wait_seconds", 0.35)))
    tap(adb, device, *device_boss["radar_first_target_point"])


def loot_motion_cycle(adb: str, device: str, device_boss: dict, cfg: dict, runtime: WorldBossRuntime):
    """Continuously pick up while making a short collision-resistant 8-way move."""
    pickup = device_boss["pickup_point"]
    count = int(cfg.get("pickup_burst_count", 8))
    delay = float(cfg.get("pickup_burst_delay_seconds", 0.06))
    first = max(1, count // 2)
    burst_tap(adb, device, pickup, first, delay)
    directions = device_boss["loot_micro_move_points"]
    end = directions[runtime.motion_index % len(directions)]
    runtime.motion_index += 1
    swipe(
        adb,
        device,
        device_boss["joystick_center"],
        end,
        int(cfg.get("loot_micro_move_duration_ms", 180)),
    )
    burst_tap(adb, device, pickup, max(1, count - first), delay)


def world_boss_tick(
    image: Image.Image,
    monotonic_now: float,
    wall_now: datetime,
    adb: str,
    device: str,
    global_cfg: dict,
    device_cfg: dict,
    runtime: WorldBossRuntime,
    logger,
) -> str:
    cfg = global_cfg.get("world_boss", {})
    device_boss = device_cfg.get("world_boss", {})
    if not cfg.get("enabled", False) or not device_boss.get("enabled", False):
        return runtime.state
    if monotonic_now < runtime.suppress_until:
        return runtime.state

    actions_enabled = not global_cfg["dry_run"] and device_cfg.get("actions_enabled", False)
    elapsed = monotonic_now - runtime.state_since
    if runtime.state == "idle":
        slot = world_boss_schedule_slot(wall_now, cfg)
        signature = bool(slot) and world_boss_icon_visible(image, cfg)
        runtime.icon_frames = runtime.icon_frames + 1 if signature else 0
        if (
            slot
            and slot != runtime.completed_slot
            and runtime.icon_frames >= int(cfg.get("icon_confirm_frames", 3))
        ):
            logger.warning("world boss icon signature confirmed slot=%s", slot)
            if cfg.get("observe_only", False):
                evidence = save_evidence(
                    image,
                    ROOT / global_cfg["evidence_directory"],
                    device,
                    "world-boss-icon-candidate",
                )
                logger.warning("world boss observe-only candidate saved: %s", evidence)
                runtime.icon_frames = 0
                runtime.suppress_until = monotonic_now + float(cfg.get("observe_cooldown_seconds", 30))
                return runtime.state
            if actions_enabled:
                tap(adb, device, *device_boss["icon_point"])
                save_world_boss_marker(device, slot)
            runtime.completed_slot = slot
            runtime.state = "menu"
            runtime.state_since = monotonic_now
            runtime.last_action = monotonic_now
            runtime.icon_frames = 0
    elif runtime.state == "menu" and elapsed >= float(cfg["menu_wait_seconds"]):
        logger.info("world boss entry button")
        if actions_enabled:
            tap(adb, device, *device_boss["entry_point"])
        runtime.state = "arena_wait"
        runtime.state_since = monotonic_now
        runtime.last_action = monotonic_now
    elif runtime.state == "arena_wait":
        if elapsed >= float(cfg["buff_delay_seconds"]) and runtime.last_action == runtime.state_since:
            logger.info("world boss buffs: Immune to Harm then Dragon Pearl")
            if actions_enabled:
                burst_tap(adb, device, device_boss["immune_scroll_point"], 1, 0.25)
                burst_tap(adb, device, device_boss["dragon_pearl_point"], 1, 0.25)
            runtime.last_action = monotonic_now
        if elapsed >= float(cfg["attack_delay_seconds"]):
            logger.info("world boss radar target row 1 acquisition and AUTO")
            if actions_enabled:
                radar_select_first_target(adb, device, device_boss, logger)
                tap(adb, device, *device_boss["attack_point"])
                active = is_auto_active(
                    screenshot(adb, device),
                    device_boss["auto_region"],
                    int(device_boss["minimum_auto_orange_pixels"]),
                )
                if not active:
                    tap(adb, device, *device_boss["auto_point"])
            runtime.state = "combat"
            runtime.state_since = monotonic_now
            runtime.last_action = monotonic_now
    elif runtime.state == "combat":
        loot_pixels = count_loot_text(image, cfg["loot_region"])
        if elapsed >= float(cfg["minimum_combat_seconds"]) and loot_pixels >= int(cfg["minimum_loot_text_pixels"]):
            runtime.loot_frames += 1
        else:
            runtime.loot_frames = 0
        if runtime.loot_frames >= int(cfg.get("loot_confirm_frames", 2)):
            logger.warning("world boss death/drop detected loot_pixels=%s", loot_pixels)
            runtime.state = "loot"
            runtime.state_since = monotonic_now
            runtime.last_action = 0.0
            runtime.loot_empty_frames = 0
            runtime.motion_index = 0
            if actions_enabled:
                execute_actions(adb, device, [{
                    "type": "ensure_auto_off",
                    "point": device_boss["auto_point"],
                    "region": device_boss["auto_region"],
                    "minimum_orange_pixels": device_boss["minimum_auto_orange_pixels"],
                    "label": "disable AUTO before continuous world-boss pickup",
                }], logger)
        elif monotonic_now - runtime.last_action >= float(cfg["reacquire_seconds"]):
            if actions_enabled:
                radar_select_first_target(adb, device, device_boss, logger)
                tap(adb, device, *device_boss["attack_point"])
            runtime.last_action = monotonic_now
    elif runtime.state == "loot":
        loot_pixels = count_loot_text(image, cfg["loot_region"])
        if elapsed >= float(cfg.get("minimum_loot_seconds", 5.0)):
            if loot_pixels < int(cfg["minimum_loot_text_pixels"]):
                runtime.loot_empty_frames += 1
            else:
                runtime.loot_empty_frames = 0
        finished = (
            elapsed > float(cfg["loot_duration_seconds"])
            or runtime.loot_empty_frames >= int(cfg.get("loot_empty_confirm_frames", 4))
        )
        if not finished:
            if actions_enabled:
                loot_motion_cycle(adb, device, device_boss, cfg, runtime)
        else:
            logger.info(
                "world boss loot complete elapsed=%.1f empty_frames=%s; return and resume",
                elapsed,
                runtime.loot_empty_frames,
            )
            if actions_enabled:
                recover_and_resume(adb, device, device_cfg, logger)
            runtime.state = "idle"
            runtime.suppress_until = monotonic_now + float(cfg["completion_cooldown_seconds"])
            runtime.state_since = monotonic_now
            runtime.loot_frames = 0
            runtime.loot_empty_frames = 0
    return runtime.state


def return_to_town(adb: str, device: str, device_cfg: dict, logger) -> bool:
    """Issue return and retry quickly until the safe-zone label is visible."""
    attempts = int(device_cfg.get("return_retry_attempts", 3))
    timeout = float(device_cfg.get("return_verify_timeout_seconds", 2.5))
    interval = float(device_cfg.get("return_verify_interval_seconds", 0.2))
    minimum = int(device_cfg.get("safe_zone_cyan_pixels", 150))
    for attempt in range(1, attempts + 1):
        logger.warning("return attempt %s/%s", attempt, attempts)
        execute_actions(adb, device, device_cfg["return_actions"], logger)
        deadline = time.monotonic() + timeout
        safe = 0
        while time.monotonic() < deadline:
            frame = screenshot(adb, device)
            safe = count_safe_zone_color(frame, device_cfg["regions"]["zone_label"])
            if safe >= minimum:
                logger.info("return verified safe=%s minimum=%s attempt=%s", safe, minimum, attempt)
                return True
            time.sleep(interval)
        logger.error("return attempt %s failed safe=%s minimum=%s", attempt, safe, minimum)
    return False


def recover_and_resume(adb: str, device: str, device_cfg: dict, logger):
    """Return to town, finish mandatory town chores, then resume hunting."""
    if "regions" in device_cfg and not return_to_town(adb, device, device_cfg, logger):
        logger.critical("all return attempts failed; follow-up clicks aborted")
        return None
    if "regions" not in device_cfg:
        execute_actions(adb, device, device_cfg["return_actions"], logger)
    fixed_town_actions = device_cfg.get("fixed_town_actions", [])
    if fixed_town_actions and not execute_actions(adb, device, fixed_town_actions, logger):
        logger.error("fixed-town routing failed; town chores aborted")
        return None
    if device_cfg.get("town_actions_enabled", True):
        if not execute_actions(adb, device, device_cfg.get("town_actions", []), logger):
            logger.error("town routine verification failed; hunting route aborted")
            return None
    else:
        logger.info("town NPC clicks disabled; waiting for safe HP recovery")
        deadline = time.monotonic() + float(device_cfg.get("town_recovery_timeout_seconds", 60))
        target = float(device_cfg.get("town_recovery_hp_ratio", 0.90))
        while time.monotonic() < deadline:
            hp = measure_hp(screenshot(adb, device), device_cfg["regions"]["hp_bar"])
            logger.info("town recovery hp=%.3f target=%.3f", hp, target)
            if hp >= target:
                break
            time.sleep(1.0)
        execute_actions(adb, device, device_cfg.get("recovery_cleanup_actions", []), logger)
    routes = device_cfg["hunting_routes"]
    round_robin = device_cfg.get("hunting_route_mode") == "round_robin"
    route_index = load_hunting_route_index(device, len(routes)) if round_robin else -1
    route = routes[route_index] if round_robin else random.choice(routes)
    logger.info(
        "%s hunting route selected: %s",
        "alternating" if round_robin else "random",
        route.get("name", ""),
    )
    completed = execute_actions(adb, device, route["actions"], logger)
    if round_robin and completed:
        save_hunting_route_index(device, (route_index + 1) % len(routes))
    return route


def recover_after_death(adb: str, device: str, device_cfg: dict, logger):
    """Restart after death, recover safely, perform town chores, and hunt again."""
    point = device_cfg.get("death_restart_point", [640, 570])
    logger.critical("death panel detected; restarting character at %s", point)
    tap(adb, device, *point)
    time.sleep(float(device_cfg.get("death_restart_load_seconds", 5.0)))

    target = float(device_cfg.get("death_recovery_hp_ratio", 0.90))
    deadline = time.monotonic() + float(device_cfg.get("death_recovery_timeout_seconds", 180))
    recovered_frames = 0
    while time.monotonic() < deadline:
        frame = screenshot(adb, device)
        safe = count_safe_zone_color(frame, device_cfg["regions"]["zone_label"])
        hp = measure_hp(frame, device_cfg["regions"]["hp_bar"])
        logger.info("death recovery hp=%.3f safe=%s target=%.3f", hp, safe, target)
        if safe >= int(device_cfg.get("safe_zone_cyan_pixels", 150)) and hp >= target:
            recovered_frames += 1
            if recovered_frames >= 2:
                break
        else:
            recovered_frames = 0
        time.sleep(2.0)
    if recovered_frames < 2:
        logger.error("death recovery timed out; remaining in safe town without risky clicks")
        return None

    fixed = device_cfg.get("fixed_town_actions", [])
    if fixed and not execute_actions(adb, device, fixed, logger):
        return None
    if device_cfg.get("town_actions_enabled", True):
        if not execute_actions(adb, device, device_cfg.get("town_actions", []), logger):
            return None
    routes = device_cfg["hunting_routes"]
    index = load_hunting_route_index(device, len(routes))
    route = routes[index]
    logger.info("post-death hunting route selected: %s", route.get("name", ""))
    completed = execute_actions(adb, device, route["actions"], logger)
    if completed:
        save_hunting_route_index(device, (index + 1) % len(routes))
    return route if completed else None


def recover_quest_to_town(adb: str, device: str, device_cfg: dict, logger):
    """Quest mode must never choose a normal hunting route after escape."""
    if "regions" in device_cfg and not return_to_town(adb, device, device_cfg, logger):
        logger.critical("all quest return attempts failed; follow-up clicks aborted")
        return None
    if "regions" not in device_cfg:
        execute_actions(adb, device, device_cfg["return_actions"], logger)
    fixed_town_actions = device_cfg.get("fixed_town_actions", [])
    if fixed_town_actions:
        execute_actions(adb, device, fixed_town_actions, logger)
    execute_actions(adb, device, device_cfg.get("town_actions", []), logger)
    logger.warning("quest recovery complete; normal hunting route intentionally skipped")


def quest_mode_enabled(global_cfg: dict) -> bool:
    """Quest mode is opt-in; a stale marker must never change normal hunting."""
    marker = global_cfg.get("quest_mode_marker")
    if not marker:
        return False
    try:
        payload = json.loads((ROOT / marker).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return payload.get("enabled") is True and payload.get("mode") == "daily-quests"


def device_loop(global_cfg: dict, device_cfg: dict, once: bool = False):
    adb = global_cfg["adb_path"]
    device = device_cfg["device"]
    interval = float(global_cfg["poll_interval_seconds"])
    output = ROOT / global_cfg["evidence_directory"]
    history: deque[FrameState] = deque(maxlen=30)
    cooldown_until = 0.0
    logger = logging.getLogger(device)
    world_boss = WorldBossRuntime(completed_slot=load_world_boss_marker(device))
    auto_watchdog_at = 0.0

    while True:
        image = screenshot(adb, device)
        now = time.monotonic()
        if is_death_panel_visible(image, device_cfg):
            evidence = save_evidence(image, output, device, "death")
            logger.critical("death detected evidence=%s", evidence)
            if not global_cfg["dry_run"] and device_cfg.get("actions_enabled", False):
                recover_after_death(adb, device, device_cfg, logger)
            history.clear()
            world_boss.state = "idle"
            auto_watchdog_at = time.monotonic() + 10.0
            if once:
                return None
            time.sleep(interval)
            continue
        state = FrameState(
            timestamp=now,
            hp_ratio=measure_hp(image, device_cfg["regions"]["hp_bar"]),
            cyan_pixels=count_cyan(image, device_cfg["regions"]["world_player_names"]),
            hostile_magenta_pixels=count_hostile_magenta(
                image, device_cfg["regions"]["world_player_names"]
            ),
            pvp_red_pixels=count_pvp_red(
                image, device_cfg["regions"]["pvp_indicator"]
            ),
            safe_zone_pixels=count_safe_zone_color(
                image, device_cfg["regions"]["zone_label"]
            ),
        )
        history.append(state)
        quest_mode = quest_mode_enabled(global_cfg)
        threat, reason = detect_threat(
            history,
            global_cfg,
            emergency_in_safe_zone=world_boss.state not in ("idle",),
            emergency_only=quest_mode,
        )
        logger.info("state %s threat=%s", reason, threat)

        if threat and now >= cooldown_until:
            evidence = save_evidence(image, output, device, "threat")
            logger.warning("PvP threat detected: %s evidence=%s", reason, evidence)
            if global_cfg["dry_run"] or not device_cfg.get("actions_enabled", False):
                logger.warning(
                    "actions disabled: dry_run=%s device.actions_enabled=%s",
                    global_cfg["dry_run"],
                    device_cfg.get("actions_enabled", False),
                )
            else:
                if quest_mode:
                    recover_quest_to_town(adb, device, device_cfg, logger)
                else:
                    recover_and_resume(adb, device, device_cfg, logger)
            world_boss.state = "idle"
            world_boss.suppress_until = now + float(
                global_cfg.get("world_boss", {}).get("completion_cooldown_seconds", 3600)
            )
            cooldown_until = now + float(global_cfg["detection"]["cooldown_seconds"])
            history.clear()

        if not threat:
            world_boss_tick(
                image,
                now,
                datetime.now(),
                adb,
                device,
                global_cfg,
                device_cfg,
                world_boss,
                logger,
            )

        safe_minimum = int(device_cfg.get("safe_zone_cyan_pixels", 150))
        field_ready = state.hp_ratio > 0.40 and state.safe_zone_pixels < safe_minimum
        menus_closed = (
            not is_main_menu_open(image, [900, 80, 1270, 680])
            and not is_close_overlay_open(image, [1200, 5, 1270, 75])
        )
        if (
            not threat
            and world_boss.state == "idle"
            and field_ready
            and menus_closed
            and now >= auto_watchdog_at
        ):
            boss_cfg = device_cfg.get("world_boss", {})
            execute_actions(adb, device, [{
                "type": "ensure_auto",
                "point": boss_cfg.get("auto_point", [998, 548]),
                "region": boss_cfg.get("auto_region", [960, 500, 1040, 590]),
                "minimum_orange_pixels": boss_cfg.get("minimum_auto_orange_pixels", 500),
                "sample_count": 2,
                "sample_interval_seconds": 0.15,
                "label": "field idle watchdog keeps hunting active",
            }], logger)
            auto_watchdog_at = now + float(device_cfg.get("auto_watchdog_seconds", 8.0))

        if once:
            return state
        time.sleep(interval)


def validate(config: dict):
    if not Path(config["adb_path"]).exists():
        raise FileNotFoundError(f"ADB not found: {config['adb_path']}")
    if not config.get("devices"):
        raise ValueError("at least one device must be configured")
    for device in config["devices"]:
        for name in ("hp_bar", "world_player_names", "pvp_indicator", "zone_label"):
            rect = device["regions"][name]
            if len(rect) != 4 or rect[2] <= rect[0] or rect[3] <= rect[1]:
                raise ValueError(f"invalid {name} region for {device['device']}: {rect}")
        if not config["dry_run"] and not device.get("hunting_routes"):
            raise ValueError(f"no hunting routes configured for {device['device']}")


def resolve_device_config(config: dict, device: dict) -> dict:
    """Let a test emulator reuse calibrated UI actions without enabling its source."""
    source_name = device.get("inherits_from")
    if not source_name:
        return device
    source = next((item for item in config["devices"] if item.get("name") == source_name), None)
    if source is None:
        raise ValueError(f"unknown inherited device config: {source_name}")
    resolved = copy.deepcopy(source)
    calibrated_keys = {"regions", "return_actions", "fixed_town_actions", "town_actions", "hunting_routes"}
    resolved.update({
        key: value for key, value in device.items()
        if key not in calibrated_keys | {"inherits_from", "world_boss"}
    })
    if "world_boss" in device:
        resolved["world_boss"].update(device["world_boss"])
    return resolved


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
    devices = [resolve_device_config(config, item) for item in config["devices"]]
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
                f"cyan={state.cyan_pixels} hostile={state.hostile_magenta_pixels} "
                f"pvp_red={state.pvp_red_pixels} safe={state.safe_zone_pixels}"
            )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
