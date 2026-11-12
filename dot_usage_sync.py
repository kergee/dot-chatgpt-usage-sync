#!/usr/bin/env python3
"""Sync Codex Plus usage to a Dot Canvas device without an LLM call."""

from __future__ import annotations

import argparse
import ctypes
import getpass
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import winreg
from datetime import datetime, timedelta, timezone


DEFAULT_TASK_NAME = "Dot ChatGPT Plus Usage"
TIME_ZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
ROOT_PATH = Path(__file__).resolve().parent
DATA_PATH = ROOT_PATH / "data"
CONFIG_PATH = ROOT_PATH / "config.json"
TEMPLATE_PATH = ROOT_PATH / "canvas-template.json"
PAYLOAD_PATH = DATA_PATH / "canvas-payload.json"
LOG_PATH = DATA_PATH / "sync.log"
QUOTES = (
    "循此苦旅\n以达繁星",
    "自尘至星\n本无坦途",
    "道阻且长\n行则将至",
    "艰难困苦\n玉汝于成",
    "一息尚存\n希望不灭",
    "宁折不屈\n功不唐捐",
    "行而愈强\n艰险砺德",
    "凭己之力\n振翅高飞",
    "千淘万漉\n始见真金",
    "宝剑磨砺\n梅花苦寒",
    "路漫漫兮\n上下求索",
    "乘风而起\n破浪万里",
    "越是艰难\n越要修心",
    "会当凌绝顶\n一览众山小",
    "欲穷千里目\n更上一层楼",
    "生当作人杰\n死亦为鬼雄",
    "及时当勉励\n岁月不待人",
    "读书破万卷\n下笔如有神",
    "野火烧不尽\n春风吹又生",
    "精诚所至\n金石为开",
    "锲而不舍\n金石可镂",
    "功崇惟志\n业广惟勤",
    "为者常成\n行者常至",
    "丈夫志四海\n万里犹比邻",
)

def log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(TIME_ZONE).isoformat(timespec="seconds")
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(f"{timestamp} {message}\n")


def find_codex_executable() -> Path:
    override = os.environ.get("CODEX_EXE")
    if override and Path(override).is_file():
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is not set")
    candidates = list((Path(local_app_data) / "OpenAI" / "Codex" / "bin").glob("*/codex.exe"))
    candidates = [candidate for candidate in candidates if candidate.is_file()]
    if not candidates:
        raise RuntimeError("codex.exe was not found")
    return max(candidates, key=lambda candidate: candidate.stat().st_mtime)


def read_user_environment(name: str) -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value) if value else None
    except FileNotFoundError:
        return None


def write_user_environment(name: str, value: str) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A
    SMTO_ABORTIFHUNG = 0x0002
    ctypes.windll.user32.SendMessageTimeoutW(
        HWND_BROADCAST,
        WM_SETTINGCHANGE,
        0,
        "Environment",
        SMTO_ABORTIFHUNG,
        5000,
        None,
    )


def get_dot_api_key(prompt: bool = False) -> str:
    key = os.environ.get("DOT_API_KEY") or read_user_environment("DOT_API_KEY")
    if not key and prompt:
        key = getpass.getpass("Paste DOT_API_KEY (input is hidden): ").strip()
        if key:
            write_user_environment("DOT_API_KEY", key)
    if not key:
        raise RuntimeError("DOT_API_KEY is not configured")
    return key


def read_config_file() -> dict:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Invalid configuration file: {CONFIG_PATH}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"Invalid configuration file: {CONFIG_PATH}")
    return value


def load_config(prompt: bool = False) -> dict[str, str]:
    stored = read_config_file()
    config = {
        "deviceId": (os.environ.get("DOT_DEVICE_ID") or stored.get("deviceId") or "").strip(),
        "taskKey": (os.environ.get("DOT_TASK_KEY") or stored.get("taskKey") or "").strip(),
        "taskName": (
            os.environ.get("DOT_TASK_NAME") or stored.get("taskName") or DEFAULT_TASK_NAME
        ).strip(),
    }
    if prompt:
        if not config["deviceId"]:
            config["deviceId"] = input("Dot device ID: ").strip()
        if not config["taskKey"]:
            config["taskKey"] = input("Dot Canvas task key: ").strip()
    if not config["deviceId"] or not config["taskKey"]:
        raise RuntimeError(
            f"Dot device configuration is missing. Run this script with --install or create {CONFIG_PATH}"
        )
    if prompt or not CONFIG_PATH.is_file():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return config


def configured_task_name() -> str:
    stored = read_config_file()
    return str(
        os.environ.get("DOT_TASK_NAME") or stored.get("taskName") or DEFAULT_TASK_NAME
    ).strip()


class AppServerClient:
    def __init__(self) -> None:
        environment = os.environ.copy()
        user_profile = environment.get("USERPROFILE")
        if user_profile:
            environment.setdefault("HOME", user_profile)
            environment.setdefault("CODEX_HOME", str(Path(user_profile) / ".codex"))
        self.process = subprocess.Popen(
            [str(find_codex_executable()), "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=environment,
        )
        self.responses: queue.Queue[dict] = queue.Queue()
        self.stderr: list[str] = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            try:
                self.responses.put(json.loads(line))
            except json.JSONDecodeError:
                continue

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            self.stderr.append(line.rstrip())

    def send(self, message: dict) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def request(self, request_id: int, method: str, params: dict | None, timeout: float = 20) -> dict:
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Codex app-server timed out during {method}")
            try:
                message = self.responses.get(timeout=remaining)
            except queue.Empty as error:
                raise TimeoutError(f"Codex app-server timed out during {method}") from error
            if message.get("id") != request_id:
                continue
            if message.get("error"):
                raise RuntimeError(f"Codex app-server error: {message['error']}")
            return message.get("result") or {}

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
        if self.stderr:
            log("app-server: " + " | ".join(self.stderr[-5:]))


def read_rate_limits() -> dict:
    client = AppServerClient()
    try:
        client.request(
            1,
            "initialize",
            {
                "clientInfo": {"name": "dot-usage-sync", "version": "1.0.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        client.send({"method": "initialized"})
        return client.request(
            2,
            "account/rateLimits/read",
            {"excludeResetCreditDetails": True, "supportsLunaReserve": False},
        )
    finally:
        client.close()


def format_reset(unix_seconds: int, include_date: bool) -> str:
    value = datetime.fromtimestamp(unix_seconds, TIME_ZONE)
    return value.strftime("%m/%d %H:%M" if include_date else "%H:%M")


def window_label(window: dict) -> str:
    minutes = int(window.get("windowDurationMins") or 0)
    if minutes == 300:
        return "5 小时"
    if minutes == 10080:
        return "本周"
    if minutes and minutes % 1440 == 0:
        return f"{minutes // 1440} 天"
    if minutes and minutes % 60 == 0:
        return f"{minutes // 60} 小时"
    return "当前周期"


def window_fields(window: dict, include_date: bool) -> tuple[str, str, str]:
    used = round(window["usedPercent"])
    remaining = max(0, 100 - used)
    reset = format_reset(window["resetsAt"], include_date)
    return f"{remaining}%", f"已用 {used}%", f"{reset} 重置"


def usage_status(remaining: int) -> str:
    if remaining >= 90:
        return "满格"
    if remaining >= 60:
        return "充足"
    if remaining >= 30:
        return "留意"
    return "紧张"


def choose_quote(previous: str = "") -> str:
    valid_quotes = []
    for quote in QUOTES:
        lines = quote.splitlines()
        if len(lines) == 2 and all(line and len(line) <= 6 for line in lines):
            valid_quotes.append(quote)
    if not valid_quotes:
        return "道阻且长\n行则将至"
    choices = [quote for quote in valid_quotes if quote != previous]
    return secrets.choice(choices or valid_quotes)


def save_payload(payload: dict) -> None:
    PAYLOAD_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PAYLOAD_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(PAYLOAD_PATH)


def load_payload() -> dict:
    source = PAYLOAD_PATH if PAYLOAD_PATH.is_file() else TEMPLATE_PATH
    if not source.is_file():
        raise RuntimeError(f"Canvas template is missing: {TEMPLATE_PATH}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Invalid Canvas payload: {source}") from error
    if not isinstance(payload, dict) or "data" not in payload or "windowData" not in payload:
        raise RuntimeError(f"Invalid Canvas payload: {source}")
    return payload


def configure_secondary_panel(payload: dict, quote_mode: bool) -> None:
    """Switch the right panel between a large metric and a two-line quote."""
    label_props = None
    value_props = None

    def visit(node: object) -> None:
        nonlocal label_props, value_props
        if isinstance(node, dict):
            props = node.get("props")
            if isinstance(props, dict):
                children = props.get("children")
                if isinstance(children, str):
                    if 'get inputData "weekLabel"' in children:
                        label_props = props
                    elif 'get inputData "weekRemaining"' in children:
                        value_props = props
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(payload.get("windowData", {}))
    if label_props is None or value_props is None:
        raise RuntimeError("Secondary panel was not found in the Canvas layout")

    if quote_mode:
        label_props["tw"] = "text-12-chillduansans"
        value_props["tw"] = (
            "flex flex-1 items-center justify-center text-center "
            "text-18-chillduansans font-bold"
        )
        value_props["style"] = {
            "lineHeight": "24px",
            "whiteSpace": "pre-line",
            "letterSpacing": "1px",
            "lineClamp": 2,
            "overflow": "hidden",
        }
    else:
        label_props["tw"] = "text-14-chillduansans"
        value_props["tw"] = "text-32-chillduansans font-bold"
        value_props["style"] = {"lineHeight": "38px"}


def update_payload(rate_limits: dict, task_key: str) -> dict:
    snapshots = rate_limits.get("rateLimitsByLimitId") or {}
    snapshot = snapshots.get("codex") or rate_limits.get("rateLimits")
    if not snapshot or not snapshot.get("primary"):
        raise RuntimeError("Codex rate-limit window is unavailable")
    primary = snapshot["primary"]
    secondary = snapshot.get("secondary")

    payload = load_payload()
    primary_remaining, primary_used, primary_reset = window_fields(primary, True)
    account_id = str(rate_limits.get("accountId") or "")
    account_suffix = account_id[-4:] if account_id else "未知"
    plan_type = str(snapshot.get("planType") or "").upper()
    payload["data"].update(
        {
            "title": f"ChatGPT {plan_type or '用量'}",
            "shortLabel": window_label(primary),
            "shortRemaining": primary_remaining,
            "shortUsed": primary_used,
            "shortReset": primary_reset,
            "updated": f"更新 {datetime.now(TIME_ZONE):%H:%M}",
        }
    )
    if secondary:
        payload["data"]["quote"] = ""
        secondary_remaining, secondary_used, secondary_reset = window_fields(secondary, True)
        payload["data"].update(
            {
                "weekLabel": window_label(secondary),
                "weekRemaining": secondary_remaining,
                "weekUsed": secondary_used,
                "weekReset": secondary_reset,
            }
        )
        configure_secondary_panel(payload, quote_mode=False)
    else:
        quote = choose_quote(str(payload["data"].get("quote") or ""))
        payload["data"].update(
            {
                "quote": quote,
                "weekLabel": "今日格言",
                "weekRemaining": quote,
                "weekUsed": plan_type or "套餐未知",
                "weekReset": f"账号 · {account_suffix}",
            }
        )
        configure_secondary_panel(payload, quote_mode=True)
    payload["taskKey"] = task_key
    payload["refreshNow"] = True

    save_payload(payload)
    return payload


def update_quote_only(task_key: str) -> dict:
    payload = load_payload()
    current = str(payload.get("data", {}).get("quote") or "")
    quote = choose_quote(current)
    payload["data"]["quote"] = quote
    payload["data"]["weekLabel"] = "今日格言"
    payload["data"]["weekRemaining"] = quote
    configure_secondary_panel(payload, quote_mode=True)
    payload["taskKey"] = task_key
    payload["refreshNow"] = True
    save_payload(payload)
    return payload


def send_to_dot(payload: dict, api_key: str, device_id: str) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"https://dot.mindreset.tech/api/authV2/open/device/{device_id}/canvas",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Dot API HTTP {error.code}: {detail}") from error


def sync() -> None:
    config = load_config()
    api_key = get_dot_api_key()
    rate_limits = None
    try:
        rate_limits = read_rate_limits()
        payload = update_payload(rate_limits, config["taskKey"])
    except Exception as error:
        payload = update_quote_only(config["taskKey"])
        log(f"WARNING: usage refresh failed; retained prior usage and rotated quote: {error}")
    send_to_dot(payload, api_key, config["deviceId"])
    if rate_limits:
        account_suffix = str(rate_limits.get("accountId") or "unknown")[-4:]
        log(
            f"updated account ...{account_suffix}: "
            f"{payload['data']['shortLabel']} {payload['data']['shortRemaining']} remaining; "
            f"quote: {payload['data']['quote']}"
        )
    else:
        log(f"updated quote only: {payload['data']['quote']}")


def install() -> None:
    config = load_config(prompt=True)
    task_name = config["taskName"]
    get_dot_api_key(prompt=True)
    script_path = Path(__file__).resolve()
    scheduled_python = Path(sys.executable).with_name("pythonw.exe")
    if not scheduled_python.is_file():
        scheduled_python = Path(sys.executable)
    action = subprocess.list2cmdline([str(scheduled_python), str(script_path), "--sync"])
    subprocess.run(
        [
            "schtasks.exe",
            "/Create",
            "/TN",
            task_name,
            "/TR",
            action,
            "/SC",
            "MINUTE",
            "/MO",
            "15",
            "/F",
            "/RL",
            "LIMITED",
        ],
        check=True,
    )
    sync()
    print(f"Installed and started scheduled task: {task_name}")
    print(f"Config: {CONFIG_PATH}")
    print(f"Log: {LOG_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--install", action="store_true", help="Install and start the 15-minute task")
    mode.add_argument("--sync", action="store_true", help="Run one synchronization")
    mode.add_argument("--uninstall", action="store_true", help="Delete the scheduled task")
    args = parser.parse_args()
    try:
        if args.install:
            install()
        elif args.uninstall:
            task_name = configured_task_name()
            subprocess.run(["schtasks.exe", "/Delete", "/TN", task_name, "/F"], check=True)
            print(f"Deleted scheduled task: {task_name}")
        else:
            sync()
    except Exception as error:
        log(f"ERROR: {error}")
        if sys.stderr is not None:
            print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
