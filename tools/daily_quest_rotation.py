#!/usr/bin/env python3
"""Persistent policy and recorded switching for four-character daily quests."""

from __future__ import annotations
import argparse, io, json, subprocess, time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "daily_quest_rotation.json"

@dataclass
class RotationState:
    day: str
    active_character: str
    completed: dict[str, list[str]] = field(default_factory=dict)
    def complete(self, character: str, task: str) -> None:
        tasks = self.completed.setdefault(character, [])
        if task not in tasks: tasks.append(task)

def new_state(config: dict, today: date | None = None) -> RotationState:
    chars = config["characters"]
    return RotationState((today or date.today()).isoformat(), chars[0]["name"], {c["name"]: [] for c in chars})

def state_path(config: dict) -> Path: return ROOT / config["state_file"]

def load_state(config: dict, today: date | None = None) -> RotationState:
    expected = (today or date.today()).isoformat()
    try:
        state = RotationState(**json.loads(state_path(config).read_text(encoding="utf-8")))
        if state.day == expected: return state
    except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError): pass
    return new_state(config, today)

def save_state(config: dict, state: RotationState) -> None:
    path = state_path(config); path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"day": state.day, "active_character": state.active_character, "completed": state.completed}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)

def character(config: dict, name: str) -> dict:
    for item in config["characters"]:
        if item["name"] == name: return item
    raise ValueError(f"unknown character: {name}")

def tasks_for(config: dict, name: str) -> list[str]:
    item = character(config, name)
    return list(config["task_policy"][item["role"]])

def next_task(config: dict, state: RotationState, name: str | None = None) -> str | None:
    selected = name or state.active_character; done = set(state.completed.get(selected, []))
    return next((task for task in tasks_for(config, selected) if task not in done), None)

def next_character(config: dict, state: RotationState) -> str:
    names = [item["name"] for item in config["characters"]]; index = names.index(state.active_character)
    return names[(index + 1) % len(names)]

def adb_tap(adb: str, device: str, point: list[int]) -> None:
    subprocess.run([adb, "-s", device, "shell", "input", "tap", str(point[0]), str(point[1])], check=True, capture_output=True, timeout=20)

def adb_screenshot(adb: str, device: str) -> Image.Image:
    result = subprocess.run([adb, "-s", device, "exec-out", "screencap", "-p"], check=True, capture_output=True, timeout=20)
    return Image.open(io.BytesIO(result.stdout)).convert("RGB")

def reward_ready(image: Image.Image, region: list[int], minimum_red_pixels: int = 1200) -> bool:
    red = 0
    for r, g, b in image.crop(tuple(region)).getdata():
        if r >= 105 and r >= g * 1.35 and r >= b * 1.25: red += 1
    return red >= minimum_red_pixels

def start_quest(config: dict, adb: str, task: str) -> None:
    """Open the proper quest tab, use 바로 가기, confirm and ensure AUTO."""
    quest = config["quest"]; device = config["device"]
    adb_tap(adb, device, quest["icon_point"]); time.sleep(.8)
    adb_tap(adb, device, quest["clan_tab_point"] if task.startswith("clan_") else quest["mission_tab_point"]); time.sleep(.5)
    adb_tap(adb, device, quest["go_points"][task]); time.sleep(.8)
    adb_tap(adb, device, quest["teleport_confirm_point"]); time.sleep(12)
    adb_tap(adb, device, [998, 548])

def donate_adena(config: dict, adb: str) -> None:
    """Perform the five verified 100,000-Adena general clan donations."""
    donation = config["donation"]; device = config["device"]
    adb_tap(adb, device, donation["menu_point"]); time.sleep(.6)
    adb_tap(adb, device, donation["clan_point"]); time.sleep(1.5)
    adb_tap(adb, device, donation["donation_page_point"]); time.sleep(.8)
    for _ in range(int(donation["count"])):
        adb_tap(adb, device, donation["adena_button_point"])
        time.sleep(float(donation["tap_delay_seconds"]))

def switch_character(config: dict, adb: str, target_name: str) -> None:
    target = character(config, target_name); flow = config["switch"]; device = config["device"]
    sequence = [(flow["return_point"], flow["town_wait_seconds"]), (flow["menu_point"], .8),
                (flow["restart_point"], .8), (flow["character_select_confirm_point"], flow["restart_wait_seconds"]),
                (target["row_point"], flow["selection_wait_seconds"]), (flow["enter_point"], flow["login_wait_seconds"])]
    for point, delay in sequence: adb_tap(adb, device, point); time.sleep(float(delay))

def describe(config: dict, state: RotationState) -> str:
    lines = [f"day={state.day} active={state.active_character}"]
    for item in config["characters"]:
        done = set(state.completed.get(item["name"], [])); pending = [t for t in tasks_for(config, item["name"]) if t not in done]
        lines.append(f"{item['name']} ({item['role']}): pending={','.join(pending) or 'none'}")
    return "\n".join(lines)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--show-plan", action="store_true"); parser.add_argument("--switch-to"); parser.add_argument("--donate-adena", action="store_true"); parser.add_argument("--adb", default=r"C:\LDPlayer\LDPlayer9\adb.exe")
    args = parser.parse_args(); config = json.loads(args.config.read_text(encoding="utf-8")); state = load_state(config)
    if args.switch_to:
        switch_character(config, args.adb, args.switch_to); state.active_character = args.switch_to; save_state(config, state)
    if args.donate_adena:
        donate_adena(config, args.adb); state.complete(state.active_character, "clan_adena_donation_5"); save_state(config, state)
    print(describe(config, state))

if __name__ == "__main__": main()
