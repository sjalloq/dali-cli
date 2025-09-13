from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, List
import time

from rich.console import Console
from rich.table import Table

from .api import Client

try:  # Python 3.11+
    import tomllib  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


def _env_default(name: str, default: str) -> str:
    return os.environ.get(name, default)


CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "dali-cli")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.toml")


def _load_config() -> dict:
    try:
        with open(CONFIG_PATH, "rb") as f:
            if tomllib is None:
                # Fallback: very small subset parser for controller.url
                data = f.read().decode("utf-8", errors="ignore")
                cfg: dict[str, Any] = {}
                sec = None
                for line in data.splitlines():
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    if s.startswith("[") and s.endswith("]"):
                        sec = s.strip("[]").strip()
                        cfg.setdefault(sec, {})
                        continue
                    if "=" in s and sec:
                        k, v = s.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"')
                        if isinstance(cfg.get(sec), dict):
                            cfg[sec][k] = v
                return cfg
            return tomllib.load(f)  # type: ignore[misc]
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _save_config(cfg: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    # Minimal writer for our known keys
    lines: list[str] = []
    ctrl = cfg.get("controller") or {}
    if ctrl:
        lines.append("[controller]")
        url = ctrl.get("url")
        if url is not None:
            lines.append(f"url = \"{str(url)}\"")
        lines.append("")
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _resolve_base_url(arg_url: str | None) -> tuple[str, str]:
    # returns (url, source). If missing, exits with a helpful message.
    if arg_url:
        return arg_url, "arg"
    cfg = _load_config()
    try:
        cfg_url = cfg.get("controller", {}).get("url")
    except Exception:
        cfg_url = None
    if isinstance(cfg_url, str) and cfg_url:
        return cfg_url, "config"
    # No fallback to env or default: require --url or config file
    msg = (
        "No controller URL configured. Provide --url or set one via\n"
        f"    dali config controller set-url http://<controller-ip>\n"
        f"Config file: {CONFIG_PATH}"
    )
    Console(stderr=True).print(f"[red]{msg}[/red]")
    raise SystemExit(2)


def _add_target_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--device", type=int, action="append", help="Target device id (repeatable)")
    ap.add_argument("--zone", type=int, action="append", help="Target zone id (repeatable)")
    ap.add_argument("--group", type=int, action="append", help="Target DALI group id (repeatable)")
    ap.add_argument("--broadcast", action="store_true", help="Target all devices (broadcast)")


def _collect_targets(args: argparse.Namespace) -> list[dict[str, int | str]]:
    targets: list[dict[str, int | str]] = []
    for d in (args.device or []):
        targets.append({"type": "device", "id": int(d)})
    for z in (args.zone or []):
        targets.append({"type": "zone", "id": int(z)})
    for g in (args.group or []):
        targets.append({"type": "group", "id": int(g)})
    if getattr(args, "broadcast", False):
        targets.append({"type": "broadcast"})
    return targets


def _add_source_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--src-device", type=int, action="append", help="Source device id (repeatable)")
    ap.add_argument("--src-group", type=int, action="append", help="Source group id (repeatable)")
    ap.add_argument("--src-d16gear", action="append", help="Source DALI gear as line:address (repeatable)")
    ap.add_argument("--src-d16group", action="append", help="Source DALI group as line:address (repeatable)")


def _collect_sources(args: argparse.Namespace) -> list[dict[str, int | str]]:
    out: list[dict[str, int | str]] = []
    for d in (getattr(args, "src_device", None) or []):
        out.append({"type": "device", "id": int(d)})
    for g in (getattr(args, "src_group", None) or []):
        out.append({"type": "group", "id": int(g)})
    def _parse_la(items: list[str] | None, typ: str) -> None:
        for s in (items or []):
            try:
                line_s, addr_s = str(s).split(":", 1)
                out.append({"type": typ, "line": int(line_s), "address": int(addr_s)})
            except Exception:
                raise SystemExit(f"Invalid {typ} format (expected line:address): {s}")
    _parse_la(getattr(args, "src_d16gear", None), "d16gear")
    _parse_la(getattr(args, "src_d16group", None), "d16group")
    return out


def cmd_devices_poll(args: argparse.Namespace) -> int:
    client = Client(base_url=args.url, timeout=args.timeout)
    results = client.poll_devices()
    # Fetch zones once to compute membership tags per device
    zone_map: dict[int, dict] = {}
    try:
        zroot = client.get_zones()
        for z in zroot.get("zones", []) or []:
            zid = z.get("id")
            if isinstance(zid, int):
                zone_map[zid] = z
    except Exception:
        pass

    if args.json:
        # enrich with zones if available
        if zone_map:
            for d in results:
                d["zones"] = _zones_for_device(d, list(zone_map.values()))
        json.dump(results, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    console = Console(stderr=False)
    table = Table(title=f"Devices (responding={sum(1 for r in results if r['reachable'])}/{len(results)})")
    table.add_column("ID", justify="right")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Line", justify="right")
    table.add_column("Addr", justify="right")
    table.add_column("Groups")
    table.add_column("Zones")
    table.add_column("Avail")
    table.add_column("LampOn")
    table.add_column("Latency", justify="right")

    for d in results:
        status = d.get("status") or {}
        groups = ",".join(map(str, d.get("groups") or []))
        zones = ",".join(_zones_for_device(d, list(zone_map.values()))) if zone_map else ""
        table.add_row(
            str(d.get("id", "")),
            str(d.get("name", "")),
            str(d.get("type", "")),
            str(d.get("line", "")),
            str(d.get("address", "")),
            groups,
            zones,
            "yes" if d.get("available") else "no",
            "on" if status.get("lampOn") else "off",
            f"{d.get('latency_ms', 0)} ms" if d.get("reachable") else "timeout",
        )

    console.print(table)
    if not results:
        console.print("[yellow]No devices returned. Try running a DALI scan first: 'dali scan start' then 'dali scan status'.[/yellow]")
    return 0


def _zones_for_device(device: dict, zones: list[dict]) -> list[str]:
    name = str(device.get("name") or "")
    did = device.get("id")
    groups = set(int(g) for g in (device.get("groups") or []) if isinstance(g, int))
    out: list[str] = []
    for z in zones:
        zname = z.get("name") or ""
        targets = z.get("targets") or []
        is_broadcast = str(zname).strip().lower() == "broadcast"
        include = False
        if is_broadcast:
            include = True
        else:
            for t in targets:
                if not isinstance(t, dict):
                    continue
                t_type = (t.get("type") or "").lower()
                t_id = t.get("id")
                if t_type in ("", "device", "default") and t_id == did:
                    include = True
                    break
                if t_type in ("group", "d16group", "dali_group", "dali-group") and isinstance(t_id, int) and t_id in groups:
                    include = True
                    break
        if include:
            out.append(str(zname or z.get("id")))
    return out


def cmd_scan_start(args: argparse.Namespace) -> int:
    client = Client(base_url=args.url, timeout=args.timeout)
    payload: dict[str, Any] = {}
    if args.new_installation:
        payload["newInstallation"] = True
    if args.no_addressing:
        payload["noAddressing"] = True
    if args.use_lines:
        payload["useLines"] = [int(x) for x in args.use_lines]
    data = client.start_scan(payload)
    Console().print({"started": True, "request": payload, "response": data})
    return 0


def cmd_scan_status(args: argparse.Namespace) -> int:
    client = Client(base_url=args.url, timeout=args.timeout)
    data = client.get_scan()
    if args.json:
        json.dump(data, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        Console().print(data)
    return 0


def cmd_scan_cancel(args: argparse.Namespace) -> int:
    client = Client(base_url=args.url, timeout=args.timeout)
    client.cancel_scan()
    Console().print({"cancelled": True})
    return 0


def cmd_scan_wait(args: argparse.Namespace) -> int:
    client = Client(base_url=args.url, timeout=args.timeout)
    console = Console(stderr=False)
    start = time.time()
    last_status: dict[str, Any] | None = None
    while True:
        try:
            st = client.get_scan()
            last_status = st
        except Exception as e:
            console.print(f"[red]Error checking scan status: {e}[/red]")
            time.sleep(args.interval)
            continue

        status = (st.get("status") or "").lower()
        progress = st.get("progress")
        found = st.get("found")
        console.print(f"status={status} progress={progress}% found={found}")

        if status in {"completed", "complete", "done"}:
            break
        if status in {"idle", "none", "stopped", "canceled", "cancelled", "error"}:
            break
        if args.timeout and (time.time() - start) > args.timeout:
            console.print("[yellow]Timeout waiting for scan to complete[/yellow]")
            break
        time.sleep(args.interval)

    if args.json and last_status is not None:
        json.dump(last_status, sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


def cmd_link(args: argparse.Namespace) -> int:
    client = Client(base_url=args.url, timeout=args.timeout)
    if args.action == "enable":
        client.link_enable()
        Console().print({"link": "enabled"})
    else:
        client.link_disable()
        Console().print({"link": "disabled"})
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dali", description="Lunatone DALI IoT CLI")
    p.add_argument("--url", default=None, help="Controller base URL (overrides config/env)")
    p.add_argument("--timeout", type=float, default=float(_env_default("DALI_TIMEOUT", "5")), help="HTTP timeout seconds")
    sub = p.add_subparsers(dest="cmd", required=True)

    # devices poll
    dp = sub.add_parser("devices", help="Device operations")
    dsp = dp.add_subparsers(dest="subcmd", required=True)
    dpp = dsp.add_parser("poll", help="Poll devices and print availability")
    dpp.add_argument("--json", action="store_true", help="Output JSON instead of a table")
    dpp.set_defaults(func=cmd_devices_poll)

    dshow = dsp.add_parser("show", help="Show a device JSON payload")
    dshow.add_argument("device_id", type=int)
    dshow.add_argument("--json", action="store_true", help="Pretty-print JSON")
    def _device_show(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        data = client.get_device(args.device_id)
        json.dump(data, sys.stdout, indent=2 if args.json else None)
        sys.stdout.write("\n")
        return 0
    dshow.set_defaults(func=_device_show)

    dtypes = dsp.add_parser("types", help="Classify device capabilities and types")
    dtypes.add_argument("--json", action="store_true")
    def _devices_types(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        root = client.get_devices()
        devices = root.get("devices", [])
        out = []
        for d in devices:
            # fetch detail for features/daliTypes if not present
            try:
                detail = client.get_device(int(d.get("id")))
            except Exception:
                detail = d
            cls = Client.classify_device(detail)
            rec = {
                "id": detail.get("id"),
                "name": detail.get("name"),
                "line": detail.get("line"),
                "address": detail.get("address"),
                "daliTypes": detail.get("daliTypes"),
                **cls,
            }
            out.append(rec)
        if args.json:
            json.dump(out, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        table = Table(title="Device Types / Capabilities")
        table.add_column("ID", justify="right")
        table.add_column("Name")
        table.add_column("Line", justify="right")
        table.add_column("Addr", justify="right")
        table.add_column("daliTypes")
        table.add_column("Kind")
        table.add_column("Switch")
        table.add_column("Dim")
        table.add_column("Color")
        for r in out:
            table.add_row(
                str(r.get("id")), r.get("name") or "", str(r.get("line", "")), str(r.get("address", "")),
                ",".join(map(str, r.get("daliTypes") or [])) or "-",
                r.get("kind") or "unknown",
                "yes" if r.get("supports_switch") else "no",
                "yes" if r.get("supports_dim") else "no",
                "yes" if r.get("supports_color") else "no",
            )
        Console().print(table)
        return 0
    dtypes.set_defaults(func=_devices_types)

    don = dsp.add_parser("on", help="Turn a device on (relay: switch, dimmer: 100%%)")
    don.add_argument("device_id", type=int)
    don.add_argument("--fade", type=float, default=0.0, help="Fade time seconds for dimmable")
    def _device_on(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        d = client.get_device(args.device_id)
        cls = Client.classify_device(d)
        payload: dict[str, Any]
        if cls.get("kind") == "relay" and not cls.get("supports_dim"):
            payload = {"switchable": True}
        else:
            if args.fade and args.fade > 0:
                payload = {"dimmableWithFade": {"dimValue": 100, "fadeTime": args.fade}}
            else:
                payload = {"dimmable": 100}
        client.control_device(args.device_id, payload)
        Console().print({"device": args.device_id, "on": True})
        return 0
    don.set_defaults(func=_device_on)

    doff = dsp.add_parser("off", help="Turn a device off (relay: switch, dimmer: 0%%)")
    doff.add_argument("device_id", type=int)
    doff.add_argument("--fade", type=float, default=0.0, help="Fade time seconds for dimmable")
    def _device_off(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        d = client.get_device(args.device_id)
        cls = Client.classify_device(d)
        payload: dict[str, Any]
        if cls.get("kind") == "relay" and not cls.get("supports_dim"):
            payload = {"switchable": False}
        else:
            if args.fade and args.fade > 0:
                payload = {"dimmableWithFade": {"dimValue": 0, "fadeTime": args.fade}}
            else:
                payload = {"dimmable": 0}
        client.control_device(args.device_id, payload)
        Console().print({"device": args.device_id, "off": True})
        return 0
    doff.set_defaults(func=_device_off)

    # scan
    sp = sub.add_parser("scan", help="Commissioning scan operations")
    ssp = sp.add_subparsers(dest="subcmd", required=True)
    ss = ssp.add_parser("start", help="Start DALI scan")
    ss.add_argument("--new-installation", action="store_true", help="Set newInstallation flag")
    ss.add_argument("--no-addressing", action="store_true", help="Set noAddressing flag")
    ss.add_argument("--use-lines", nargs="*", help="Restrict to given line numbers")
    ss.set_defaults(func=cmd_scan_start)

    sst = ssp.add_parser("status", help="Show scan status")
    sst.add_argument("--json", action="store_true", help="Output raw JSON")
    sst.set_defaults(func=cmd_scan_status)

    sc = ssp.add_parser("cancel", help="Cancel ongoing scan")
    sc.set_defaults(func=cmd_scan_cancel)

    sw = ssp.add_parser("wait", help="Wait until scan finishes")
    sw.add_argument("--interval", type=float, default=2.0, help="Polling interval seconds")
    sw.add_argument("--timeout", type=float, default=0.0, help="Overall timeout seconds (0=none)")
    sw.add_argument("--json", action="store_true", help="Print final status JSON")
    sw.set_defaults(func=cmd_scan_wait)

    # link
    lp = sub.add_parser("link", help="Enable/disable link mode")
    lp.add_argument("action", choices=["enable", "disable"], help="Link mode action")
    lp.set_defaults(func=cmd_link)

    # all-off (broadcast off)
    aoff = sub.add_parser("all-off", help="Turn all lights off (broadcast)")
    aoff.add_argument("--fade", type=float, default=0.0, help="Fade time seconds for dimmable devices")
    aoff.add_argument("--line", type=int, help="Restrict to DALI line number")
    def _all_off(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        if args.fade and args.fade > 0:
            payload = {"switchable": False, "dimmableWithFade": {"dimValue": 0, "fadeTime": args.fade}}
        else:
            payload = {"switchable": False, "dimmable": 0}
        client.control_broadcast(payload, line=args.line)
        Console().print({"broadcast": "off", "line": args.line})
        return 0
    aoff.set_defaults(func=_all_off)

    # zones
    zp = sub.add_parser("zones", help="Zone operations")
    zsp = zp.add_subparsers(dest="subcmd", required=True)

    zl = zsp.add_parser("list", help="List zones")
    def _zones_list(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        data = client.get_zones()
        zones = data.get("zones", [])
        if args.json:
            json.dump(zones, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        table = Table(title=f"Zones ({len(zones)})")
        table.add_column("ID", justify="right")
        table.add_column("Name")
        table.add_column("Targets", justify="right")
        table.add_column("FeaturesKeys", justify="right")
        for z in zones:
            feats = z.get("features") or {}
            table.add_row(str(z.get("id")), z.get("name") or "", str(len(z.get("targets") or [])), str(len(list(feats.keys()))))
        Console().print(table)
        return 0
    zl.add_argument("--json", action="store_true", help="Output raw JSON")
    zl.set_defaults(func=_zones_list)

    zi = zsp.add_parser("info", help="Show a zone detail")
    zi.add_argument("zone_id", type=int)
    def _zone_info(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        z = client.get_zone(args.zone_id)
        if args.json:
            json.dump(z, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            Console().print(z)
        return 0
    zi.add_argument("--json", action="store_true")
    zi.set_defaults(func=_zone_info)

    zs = zsp.add_parser("scenes", help="Detect scene numbers present in each zone")
    zs.add_argument("--json", action="store_true", help="Output JSON mapping")
    def _zones_scenes(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        data = client.get_zones()
        zones = data.get("zones", [])
        result = []
        for z in zones:
            nums = client.zone_scene_numbers(z)
            result.append({"id": z.get("id"), "name": z.get("name"), "scenes": nums})
        if args.json:
            json.dump(result, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        table = Table(title="Zone Scenes")
        table.add_column("ID", justify="right")
        table.add_column("Name")
        table.add_column("Scenes")
        for item in result:
            table.add_row(str(item["id"]), item.get("name") or "", ",".join(map(str, item.get("scenes") or [])) or "-")
        Console().print(table)
        return 0
    zs.set_defaults(func=_zones_scenes)

    zr = zsp.add_parser("recall", help="Recall a scene on a zone")
    zr.add_argument("zone_id", type=int)
    zr.add_argument("scene", type=int, help="Scene number (0-15)")
    zr.add_argument("--fade", type=float, default=0.0, help="Fade time seconds")
    def _zone_recall(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        if args.fade and args.fade > 0:
            payload = {"sceneWithFade": {"scene": args.scene, "fadeTime": args.fade}}
        else:
            payload = {"scene": args.scene}
        client.control_zone(args.zone_id, payload)
        Console().print({"zone": args.zone_id, "scene": args.scene, "ok": True})
        return 0
    zr.set_defaults(func=_zone_recall)

    ze = zsp.add_parser("enumerate", help="Cycle through scenes on a zone for visual identification")
    ze.add_argument("zone_id", type=int)
    ze.add_argument("--delay", type=float, default=2.0, help="Seconds to wait between scenes")
    ze.add_argument("--start", type=int, default=0, help="Start scene number")
    ze.add_argument("--end", type=int, default=15, help="End scene number (inclusive)")
    ze.add_argument("--restore", action="store_true", help="Save current to scene 15 and restore after")
    def _zone_enumerate(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        console = Console(stderr=False)
        if args.restore:
            try:
                client.control_zone(args.zone_id, {"saveToScene": 15})
                console.print("Saved current level to scene 15 for restore.")
            except Exception as e:
                console.print(f"[yellow]Warning: saveToScene failed: {e}[/yellow]")
        for s in range(args.start, args.end + 1):
            console.print(f"Recalling scene {s}...")
            try:
                client.control_zone(args.zone_id, {"scene": s})
            except Exception as e:
                console.print(f"[red]Scene {s} failed: {e}[/red]")
            time.sleep(args.delay)
        if args.restore:
            try:
                client.control_zone(args.zone_id, {"scene": 15})
                console.print("Restored scene 15.")
            except Exception as e:
                console.print(f"[yellow]Warning: restore failed: {e}[/yellow]")
        return 0
    ze.set_defaults(func=_zone_enumerate)

    zm = zsp.add_parser("members", help="List member devices of a zone")
    zm.add_argument("zone_id", type=int)
    zm.add_argument("--json", action="store_true")
    def _zone_members(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        z = client.get_zone(args.zone_id)
        members = client.zone_members(z)
        if args.json:
            json.dump(members, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        table = Table(title=f"Zone {args.zone_id} Members ({len(members)})")
        table.add_column("ID", justify="right")
        table.add_column("Name")
        table.add_column("Line", justify="right")
        table.add_column("Addr", justify="right")
        table.add_column("Groups")
        for d in members:
            table.add_row(str(d.get("id")), d.get("name") or "", str(d.get("line", "")), str(d.get("address", "")), ",".join(map(str, d.get("groups") or [])))
        Console().print(table)
        return 0
    zm.set_defaults(func=_zone_members)

    zon = zsp.add_parser("on", help="Turn a zone on (dimmable to 100, relay switch on)")
    zon.add_argument("zone_id", type=int)
    zon.add_argument("--fade", type=float, default=0.0)
    def _zone_on(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        payload: dict[str, Any]
        if args.fade and args.fade > 0:
            payload = {"switchable": True, "dimmableWithFade": {"dimValue": 100, "fadeTime": args.fade}}
        else:
            payload = {"switchable": True, "dimmable": 100}
        client.control_zone(args.zone_id, payload)
        Console().print({"zone": args.zone_id, "on": True})
        return 0
    zon.set_defaults(func=_zone_on)

    zoff = zsp.add_parser("off", help="Turn a zone off (dimmable to 0, relay switch off)")
    zoff.add_argument("zone_id", type=int)
    zoff.add_argument("--fade", type=float, default=0.0)
    def _zone_off(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        payload: dict[str, Any]
        if args.fade and args.fade > 0:
            payload = {"switchable": False, "dimmableWithFade": {"dimValue": 0, "fadeTime": args.fade}}
        else:
            payload = {"switchable": False, "dimmable": 0}
        client.control_zone(args.zone_id, payload)
        Console().print({"zone": args.zone_id, "off": True})
        return 0
    zoff.set_defaults(func=_zone_off)

    # sensors
    sp = sub.add_parser("sensors", help="Sensors operations")
    sl = sp.add_subparsers(dest="subcmd", required=True)
    slist = sl.add_parser("list", help="List sensors")
    slist.add_argument("--json", action="store_true")
    def _sensors_list(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        data = client.get_sensors()
        sensors = data.get("sensors") if isinstance(data, dict) else data
        sensors = sensors or []
        if args.json:
            json.dump(sensors, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        table = Table(title=f"Sensors ({len(sensors)})")
        table.add_column("ID", justify="right")
        table.add_column("Name")
        table.add_column("Type")
        table.add_column("Unit")
        table.add_column("Value")
        table.add_column("When")
        table.add_column("AddrType")
        for s in sensors:
            table.add_row(
                str(s.get("id")), s.get("name") or "", str(s.get("type")), s.get("unit") or "",
                str(s.get("value")), s.get("timestamp") or "", str(s.get("addressType"))
            )
        Console().print(table)
        return 0
    slist.set_defaults(func=_sensors_list)

    # automations
    ap = sub.add_parser("automations", help="Automation resources (triggers, sequences)")
    asp = ap.add_subparsers(dest="subcmd", required=True)

    # triggers
    trl = asp.add_parser("triggers", help="List trigger actions")
    trl.add_argument("--json", action="store_true")
    def _triggers_list(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        items = client.get_trigger_actions()
        if args.json:
            json.dump(items, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        table = Table(title=f"Trigger Actions ({len(items)})")
        table.add_column("ID", justify="right")
        table.add_column("Enabled")
        table.add_column("Name")
        table.add_column("Sources")
        table.add_column("Targets")
        for t in items:
            srcs = ",".join(Client.summarize_trigger_source(s) for s in (t.get("sources") or []))
            tgts = ",".join(str(x.get("id")) for x in (t.get("targets") or []) if isinstance(x, dict))
            table.add_row(str(t.get("id")), "yes" if t.get("enabled") else "no", t.get("name") or "", srcs or "-", tgts or "-")
        Console().print(table)
        return 0
    trl.set_defaults(func=_triggers_list)

    tri = asp.add_parser("trigger", help="Show one trigger action")
    tri.add_argument("trigger_id", type=int)
    tri.add_argument("--json", action="store_true")
    def _trigger_info(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        t = client.get_trigger_action(args.trigger_id)
        if args.json:
            json.dump(t, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            Console().print(t)
        return 0
    tri.set_defaults(func=_trigger_info)

    tcr = asp.add_parser("trigger-create", help="Create a trigger action")
    _add_source_args(tcr)
    _add_target_args(tcr)
    tcr.add_argument("--name", default="")
    en = tcr.add_mutually_exclusive_group()
    en.add_argument("--enabled", dest="enabled", action="store_true")
    en.add_argument("--no-enabled", dest="enabled", action="store_false")
    tcr.set_defaults(enabled=True)
    def _trigger_create(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        sources = _collect_sources(args)
        targets = _collect_targets(args)
        if not sources or not targets:
            Console().print("[red]Must provide at least one source and one target[/red]")
            return 2
        model = {"name": args.name, "enabled": bool(args.enabled), "sources": sources, "targets": targets}
        created = client.create_trigger_action(model)
        Console().print({"created": created.get("id"), "name": created.get("name") or args.name})
        return 0
    tcr.set_defaults(func=_trigger_create)

    tup = asp.add_parser("trigger-update", help="Update a trigger action")
    tup.add_argument("trigger_id", type=int)
    _add_source_args(tup)
    _add_target_args(tup)
    tup.add_argument("--name")
    upen = tup.add_mutually_exclusive_group()
    upen.add_argument("--enabled", dest="enabled", action="store_true")
    upen.add_argument("--no-enabled", dest="enabled", action="store_false")
    tup.set_defaults(enabled=None)
    def _trigger_update(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        model: dict[str, Any] = {}
        if args.name is not None:
            model["name"] = args.name
        if args.enabled is not None:
            model["enabled"] = bool(args.enabled)
        sources = _collect_sources(args)
        targets = _collect_targets(args)
        if sources:
            model["sources"] = sources
        if targets:
            model["targets"] = targets
        if not model:
            Console().print("[yellow]No fields to update[/yellow]")
            return 0
        updated = client.update_trigger_action(args.trigger_id, model)
        Console().print({"updated": updated.get("id"), "name": updated.get("name")})
        return 0
    tup.set_defaults(func=_trigger_update)

    # sequences
    sql = asp.add_parser("sequences", help="List sequences")
    sql.add_argument("--json", action="store_true")
    def _sequences_list(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        items = client.get_sequences()
        if args.json:
            json.dump(items, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        table = Table(title=f"Sequences ({len(items)})")
        table.add_column("ID", justify="right")
        table.add_column("Enabled")
        table.add_column("Name")
        table.add_column("Steps", justify="right")
        for s in items:
            steps = s.get("steps") or []
            table.add_row(str(s.get("id")), "yes" if s.get("enabled") else "no", s.get("name") or "", str(len(steps)))
        Console().print(table)
        return 0
    sql.set_defaults(func=_sequences_list)

    sqi = asp.add_parser("sequence", help="Show one sequence")
    sqi.add_argument("sequence_id", type=int)
    sqi.add_argument("--json", action="store_true")
    def _sequence_info(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        s = client.get_sequence(args.sequence_id)
        if args.json:
            json.dump(s, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        table = Table(title=f"Sequence {s.get('id')} - {s.get('name') or ''}")
        table.add_column("#", justify="right")
        table.add_column("Type")
        table.add_column("Targets")
        table.add_column("Features")
        table.add_column("Delay")
        for idx, step in enumerate(s.get("steps") or [], start=1):
            data = step.get("data") or {}
            tgts = ",".join(str(x.get("id")) for x in (data.get("targets") or []) if isinstance(x, dict))
            feats = Client.summarize_features(data.get("features") or {})
            table.add_row(str(idx), step.get("type") or "", tgts or "-", feats, str(step.get("delay") or 0))
        Console().print(table)
        return 0
    sqi.set_defaults(func=_sequence_info)

    sqst = asp.add_parser("sequence-start", help="Start a sequence")
    sqst.add_argument("sequence_id", type=int)
    def _sequence_start(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        client.start_sequence(args.sequence_id)
        Console().print({"started": args.sequence_id})
        return 0
    sqst.set_defaults(func=_sequence_start)

    sqsp = asp.add_parser("sequence-stop", help="Stop a sequence")
    sqsp.add_argument("sequence_id", type=int)
    def _sequence_stop(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        client.stop_sequence(args.sequence_id)
        Console().print({"stopped": args.sequence_id})
        return 0
    sqsp.set_defaults(func=_sequence_stop)

    sqc = asp.add_parser("sequence-create", help="Create a sequence")
    _add_target_args(sqc)
    sqc.add_argument("--name", default="")
    sqc.add_argument("--loop", action="store_true")
    sqc.add_argument("--repeat", type=int)
    en2 = sqc.add_mutually_exclusive_group()
    en2.add_argument("--enabled", dest="enabled", action="store_true")
    en2.add_argument("--no-enabled", dest="enabled", action="store_false")
    sqc.set_defaults(enabled=True)
    stepgrp = sqc.add_mutually_exclusive_group()
    stepgrp.add_argument("--on", action="store_true", help="Single step: switchable True")
    stepgrp.add_argument("--off", action="store_true", help="Single step: switchable False")
    stepgrp.add_argument("--scene", type=int, help="Single step: recall scene number")
    sqc.add_argument("--delay", type=float, default=0.0)
    sqc.add_argument("--steps-json", help="Path to JSON array of steps to use instead of single-step flags")
    def _sequence_create(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        model: dict[str, Any] = {"name": args.name, "enabled": bool(args.enabled)}
        if args.loop:
            model["loop"] = True
        if args.repeat is not None:
            model["repeat"] = int(args.repeat)
        steps: list[dict[str, Any]] = []
        if args.steps_json:
            with open(args.steps_json, "r") as f:
                steps = json.load(f)
        else:
            if not (args.on or args.off or args.scene is not None):
                Console().print("[red]Provide either --steps-json or one of --on/--off/--scene[/red]")
                return 2
            tgts = _collect_targets(args)
            if not tgts:
                Console().print("[red]Provide targets for the step using --device/--zone/--group/--broadcast[/red]")
                return 2
            feats: dict[str, Any]
            if args.on:
                feats = {"switchable": True}
            elif args.off:
                feats = {"switchable": False}
            else:
                feats = {"scene": int(args.scene)}
            steps = [{"type": "features", "data": {"targets": tgts, "features": feats}, "delay": float(args.delay)}]
        model["steps"] = steps
        created = client.create_sequence(model)
        Console().print({"created": created.get("id"), "name": created.get("name") or args.name})
        return 0
    sqc.set_defaults(func=_sequence_create)

    squ = asp.add_parser("sequence-update", help="Update a sequence")
    squ.add_argument("sequence_id", type=int)
    squ.add_argument("--name")
    squ.add_argument("--loop", dest="loop", action="store_true")
    squ.add_argument("--no-loop", dest="loop", action="store_false")
    squ.set_defaults(loop=None)
    squ.add_argument("--repeat", type=int)
    en3 = squ.add_mutually_exclusive_group()
    en3.add_argument("--enabled", dest="enabled", action="store_true")
    en3.add_argument("--no-enabled", dest="enabled", action="store_false")
    squ.set_defaults(enabled=None)
    # steps replacement
    _add_target_args(squ)
    sstep = squ.add_mutually_exclusive_group()
    sstep.add_argument("--on", action="store_true")
    sstep.add_argument("--off", action="store_true")
    sstep.add_argument("--scene", type=int)
    squ.add_argument("--delay", type=float)
    squ.add_argument("--steps-json")
    def _sequence_update(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        model: dict[str, Any] = {}
        if args.name is not None:
            model["name"] = args.name
        if args.loop is not None:
            model["loop"] = bool(args.loop)
        if args.repeat is not None:
            model["repeat"] = int(args.repeat)
        if args.enabled is not None:
            model["enabled"] = bool(args.enabled)
        # steps replacement if provided
        steps: list[dict[str, Any]] | None = None
        if args.steps_json:
            with open(args.steps_json, "r") as f:
                steps = json.load(f)
        elif args.on or args.off or (args.scene is not None):
            tgts = _collect_targets(args)
            if not tgts:
                Console().print("[red]Provide targets for the replacement step using --device/--zone/--group/--broadcast[/red]")
                return 2
            feats: dict[str, Any]
            if args.on:
                feats = {"switchable": True}
            elif args.off:
                feats = {"switchable": False}
            else:
                feats = {"scene": int(args.scene)}
            delay = float(args.delay) if args.delay is not None else 0.0
            steps = [{"type": "features", "data": {"targets": tgts, "features": feats}, "delay": delay}]
        if steps is not None:
            model["steps"] = steps
        if not model:
            Console().print("[yellow]No fields to update[/yellow]")
            return 0
        updated = client.update_sequence(args.sequence_id, model)
        Console().print({"updated": updated.get("id"), "name": updated.get("name")})
        return 0
    squ.set_defaults(func=_sequence_update)

    sqdlt = asp.add_parser("sequence-delete", help="Delete a sequence")
    sqdlt.add_argument("sequence_id", type=int)
    def _sequence_delete(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        client.delete_sequence(args.sequence_id)
        Console().print({"deleted": args.sequence_id})
        return 0
    sqdlt.set_defaults(func=_sequence_delete)

    # schedules
    sqlst = asp.add_parser("schedules", help="List schedules")
    sqlst.add_argument("--json", action="store_true")
    def _schedules_list(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        items = client.list_schedules()
        if args.json:
            json.dump(items, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        table = Table(title=f"Schedules ({len(items)})")
        table.add_column("ID", justify="right")
        table.add_column("Enabled")
        table.add_column("Name")
        table.add_column("Mode")
        table.add_column("Time")
        table.add_column("Targets")
        for s in items:
            mode = s.get("recallMode") or ""
            t = s.get("recallTime") or {}
            time_s = f"{int(t.get('hour',0)):02d}:{int(t.get('minute',0)):02d}:{int(t.get('second',0)):02d}"
            tgts = ",".join(
                f"{x.get('type')}:{x.get('id')}"
                for x in (s.get("targets") or [])
                if isinstance(x, dict)
            )
            table.add_row(
                str(s.get("id")), "yes" if s.get("enabled") else "no", s.get("name") or "",
                mode, time_s, tgts
            )
        Console().print(table)
        return 0
    sqlst.set_defaults(func=_schedules_list)

    sqdel = asp.add_parser("schedule-delete", help="Delete a schedule")
    sqdel.add_argument("schedule_id", type=int)
    def _schedule_delete(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        client.delete_schedule(args.schedule_id)
        Console().print({"deleted": args.schedule_id})
        return 0
    sqdel.set_defaults(func=_schedule_delete)

    sqstart = asp.add_parser("schedule-start", help="Start a schedule")
    sqstart.add_argument("schedule_id", type=int)
    def _schedule_start(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        client.start_schedule(args.schedule_id)
        Console().print({"started": args.schedule_id})
        return 0
    sqstart.set_defaults(func=_schedule_start)

    sqstop = asp.add_parser("schedule-stop", help="Stop a schedule")
    sqstop.add_argument("schedule_id", type=int)
    def _schedule_stop(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        client.stop_schedule(args.schedule_id)
        Console().print({"stopped": args.schedule_id})
        return 0
    sqstop.set_defaults(func=_schedule_stop)

    sqinfo = asp.add_parser("schedule", help="Show one schedule")
    sqinfo.add_argument("schedule_id", type=int)
    sqinfo.add_argument("--json", action="store_true")
    def _schedule_info(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        s = client.get_schedule(args.schedule_id)
        if args.json:
            json.dump(s, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        table = Table(title=f"Schedule {s.get('id')} - {s.get('name') or ''}")
        table.add_column("Mode")
        table.add_column("Time")
        table.add_column("Targets")
        table.add_column("Action")
        t = s.get("recallTime") or {}
        time_s = f"{int(t.get('hour',0)):02d}:{int(t.get('minute',0)):02d}:{int(t.get('second',0)):02d}"
        tgts = ",".join(f"{x.get('type')}:{x.get('id')}" for x in (s.get("targets") or []) if isinstance(x, dict))
        action = s.get("action") or {}
        action_s = f"{action.get('type')}:{Client.summarize_features(action.get('data') or {})}"
        table.add_row(s.get("recallMode") or "", time_s, tgts or "-", action_s)
        Console().print(table)
        return 0
    sqinfo.set_defaults(func=_schedule_info)

    # helpers to add dusk / off schedules
    sqdusk = asp.add_parser("schedule-add-dusk", help="Create a schedule to turn targets on at sunset")
    _add_target_args(sqdusk)
    sqdusk.add_argument("--name", default="Dusk ON")
    sqdusk.add_argument("--offset-min", type=int, default=0, help="Minutes after sunset (negative for before)")
    def _schedule_add_dusk(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        targets = _collect_targets(args)
        # afterSunset with offset: positive offset => afterSunset, negative => beforeSunset
        minutes = int(args.offset_min)
        mode = "afterSunset" if minutes >= 0 else "beforeSunset"
        minutes = abs(minutes)
        model = {
            "name": args.name,
            "targets": targets,
            "enabled": True,
            "recallMode": mode,
            "recallTime": {"hour": minutes // 60, "minute": minutes % 60, "second": 0},
            "action": {"type": "features", "data": {"switchable": True}},
        }
        created = client.create_schedule(model)
        Console().print({"created": created.get("id"), "name": created.get("name") or args.name})
        return 0
    sqdusk.set_defaults(func=_schedule_add_dusk)

    sqoff = asp.add_parser("schedule-add-off", help="Create an OFF schedule at a time or sunrise offset")
    _add_target_args(sqoff)
    sqoff.add_argument("--name", default="Night OFF")
    group = sqoff.add_mutually_exclusive_group(required=True)
    group.add_argument("--time", help="HH:MM 24h time of day")
    group.add_argument("--before-sunrise", type=int, dest="before_sunrise", help="Minutes before sunrise")
    group.add_argument("--after-sunrise", type=int, dest="after_sunrise", help="Minutes after sunrise")
    def _schedule_add_off(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        targets = _collect_targets(args)
        mode: str
        rtime: dict[str, int]
        if args.time:
            try:
                hh, mm = args.time.split(":", 1)
                mode = "timeOfDay"
                rtime = {"hour": int(hh), "minute": int(mm), "second": 0}
            except Exception:
                Console().print("[red]--time must be in HH:MM format[/red]")
                return 2
        elif args.before_sunrise is not None:
            minutes = abs(int(args.before_sunrise))
            mode = "beforeSunrise"
            rtime = {"hour": minutes // 60, "minute": minutes % 60, "second": 0}
        else:
            minutes = abs(int(args.after_sunrise or 0))
            mode = "afterSunrise"
            rtime = {"hour": minutes // 60, "minute": minutes % 60, "second": 0}
        model = {
            "name": args.name,
            "targets": targets,
            "enabled": True,
            "recallMode": mode,
            "recallTime": rtime,
            "action": {"type": "features", "data": {"switchable": False}},
        }
        created = client.create_schedule(model)
        Console().print({"created": created.get("id"), "name": created.get("name") or args.name})
        return 0
    sqoff.set_defaults(func=_schedule_add_off)

    # circadians
    cl = asp.add_parser("circadians", help="List circadian automations")
    cl.add_argument("--json", action="store_true")
    def _circadians_list(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        items = client.get_circadians()
        if args.json:
            json.dump(items, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        table = Table(title=f"Circadians ({len(items)})")
        table.add_column("ID", justify="right")
        table.add_column("Enabled")
        table.add_column("Name")
        table.add_column("Targets")
        for c in items:
            tgts = ",".join(f"{x.get('type')}:{x.get('id')}" for x in (c.get("targets") or []) if isinstance(x, dict))
            table.add_row(str(c.get("id")), "yes" if c.get("enabled") else "no", c.get("name") or "", tgts)
        Console().print(table)
        return 0
    cl.set_defaults(func=_circadians_list)

    ci = asp.add_parser("circadian", help="Show one circadian")
    ci.add_argument("circadian_id", type=int)
    ci.add_argument("--json", action="store_true")
    def _circadian_info(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        c = client.get_circadian(args.circadian_id)
        if args.json:
            json.dump(c, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        table = Table(title=f"Circadian {c.get('id')} - {c.get('name') or ''}")
        table.add_column("Targets")
        table.add_column("Enabled")
        tgts = ",".join(f"{x.get('type')}:{x.get('id')}" for x in (c.get("targets") or []) if isinstance(x, dict))
        table.add_row(tgts or "-", "yes" if c.get("enabled") else "no")
        Console().print(table)
        return 0
    ci.set_defaults(func=_circadian_info)

    cstart = asp.add_parser("circadian-start", help="Start a circadian")
    cstart.add_argument("circadian_id", type=int)
    def _circadian_start(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        client.start_circadian(args.circadian_id)
        Console().print({"started": args.circadian_id})
        return 0
    cstart.set_defaults(func=_circadian_start)

    cstop = asp.add_parser("circadian-stop", help="Stop a circadian")
    cstop.add_argument("circadian_id", type=int)
    def _circadian_stop(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        client.stop_circadian(args.circadian_id)
        Console().print({"stopped": args.circadian_id})
        return 0
    cstop.set_defaults(func=_circadian_stop)

    cdel = asp.add_parser("circadian-delete", help="Delete a circadian")
    cdel.add_argument("circadian_id", type=int)
    def _circadian_delete(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        client.delete_circadian(args.circadian_id)
        Console().print({"deleted": args.circadian_id})
        return 0
    cdel.set_defaults(func=_circadian_delete)

    ccr = asp.add_parser("circadian-create", help="Create a circadian automation")
    _add_target_args(ccr)
    ccr.add_argument("--name", default="")
    cen = ccr.add_mutually_exclusive_group()
    cen.add_argument("--enabled", dest="enabled", action="store_true")
    cen.add_argument("--no-enabled", dest="enabled", action="store_false")
    ccr.set_defaults(enabled=True)
    ccr.add_argument("--longest-json", required=True, help="Path to JSON file with the 'longest' curve")
    ccr.add_argument("--shortest-json", required=True, help="Path to JSON file with the 'shortest' curve")
    def _circadian_create(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        targets = _collect_targets(args)
        if not targets:
            Console().print("[red]Provide targets using --device/--zone/--group/--broadcast[/red]")
            return 2
        with open(args.longest_json, "r") as f:
            longest = json.load(f)
        with open(args.shortest_json, "r") as f:
            shortest = json.load(f)
        model = {"name": args.name, "enabled": bool(args.enabled), "targets": targets, "longest": longest, "shortest": shortest}
        created = client.create_circadian(model)
        Console().print({"created": created.get("id"), "name": created.get("name") or args.name})
        return 0
    ccr.set_defaults(func=_circadian_create)

    cup = asp.add_parser("circadian-update", help="Update a circadian automation")
    cup.add_argument("circadian_id", type=int)
    _add_target_args(cup)
    cup.add_argument("--name")
    uen = cup.add_mutually_exclusive_group()
    uen.add_argument("--enabled", dest="enabled", action="store_true")
    uen.add_argument("--no-enabled", dest="enabled", action="store_false")
    cup.set_defaults(enabled=None)
    cup.add_argument("--longest-json", help="Path to JSON file with the 'longest' curve")
    cup.add_argument("--shortest-json", help="Path to JSON file with the 'shortest' curve")
    def _circadian_update(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        model: dict[str, Any] = {}
        if args.name is not None:
            model["name"] = args.name
        if args.enabled is not None:
            model["enabled"] = bool(args.enabled)
        tgts = _collect_targets(args)
        if tgts:
            model["targets"] = tgts
        if args.longest_json:
            with open(args.longest_json, "r") as f:
                model["longest"] = json.load(f)
        if args.shortest_json:
            with open(args.shortest_json, "r") as f:
                model["shortest"] = json.load(f)
        if not model:
            Console().print("[yellow]No fields to update[/yellow]")
            return 0
        updated = client.update_circadian(args.circadian_id, model)
        Console().print({"updated": updated.get("id"), "name": updated.get("name")})
        return 0
    cup.set_defaults(func=_circadian_update)

    # triggers: start/stop/delete
    tstart = asp.add_parser("trigger-start", help="Start a trigger action")
    tstart.add_argument("trigger_id", type=int)
    def _trigger_start(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        client.start_trigger_action(args.trigger_id)
        Console().print({"started": args.trigger_id})
        return 0
    tstart.set_defaults(func=_trigger_start)

    tstop = asp.add_parser("trigger-stop", help="Stop a trigger action")
    tstop.add_argument("trigger_id", type=int)
    def _trigger_stop(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        client.stop_trigger_action(args.trigger_id)
        Console().print({"stopped": args.trigger_id})
        return 0
    tstop.set_defaults(func=_trigger_stop)

    tdel = asp.add_parser("trigger-delete", help="Delete a trigger action")
    tdel.add_argument("trigger_id", type=int)
    def _trigger_delete(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        client.delete_trigger_action(args.trigger_id)
        Console().print({"deleted": args.trigger_id})
        return 0
    tdel.set_defaults(func=_trigger_delete)

    # status queries
    sq = asp.add_parser("status-queries", help="DALI bus periodic status queries")
    sqsp = sq.add_subparsers(dest="action", required=True)

    sql = sqsp.add_parser("list", help="List status query configs for all lines")
    sql.add_argument("--json", action="store_true")
    def _statusq_list(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        data = client.get_status_queries()
        if args.json:
            json.dump(data, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        table = Table(title="Status Queries")
        table.add_column("Line", justify="right")
        table.add_column("Delay", justify="right")
        table.add_column("QueryStatus")
        table.add_column("QueryActualLevel")
        for line, cfg in (data or {}).items():
            table.add_row(str(line), str(cfg.get("delayBetweenQueries")), "yes" if cfg.get("queryStatus") else "no", "yes" if cfg.get("queryActualLevel") else "no")
        Console().print(table)
        return 0
    sql.set_defaults(func=_statusq_list)

    sqb = sqsp.add_parser("bounds", help="Show min/max allowed delay between queries")
    sqb.add_argument("--json", action="store_true")
    def _statusq_bounds(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        data = client.get_status_query_bounds()
        if args.json:
            json.dump(data, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            Console().print(data)
        return 0
    sqb.set_defaults(func=_statusq_bounds)

    sqg = sqsp.add_parser("get", help="Get config for one line")
    sqg.add_argument("line", type=int)
    sqg.add_argument("--json", action="store_true")
    def _statusq_get(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        data = client.get_status_queries_line(args.line)
        if args.json:
            json.dump(data, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            Console().print(data)
        return 0
    sqg.set_defaults(func=_statusq_get)

    sqs = sqsp.add_parser("set", help="Set config for one line")
    sqs.add_argument("line", type=int)
    sqs.add_argument("--delay", type=int)
    onoff = sqs.add_mutually_exclusive_group()
    onoff.add_argument("--status", dest="status", action="store_true")
    onoff.add_argument("--no-status", dest="status", action="store_false")
    onoff.set_defaults(status=None)
    alev = sqs.add_mutually_exclusive_group()
    alev.add_argument("--actual-level", dest="actual", action="store_true")
    alev.add_argument("--no-actual-level", dest="actual", action="store_false")
    alev.set_defaults(actual=None)
    def _statusq_set(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        # Get current, then update provided fields
        try:
            cfg = client.get_status_queries_line(args.line)
        except Exception:
            cfg = {}
        if args.delay is not None:
            cfg["delayBetweenQueries"] = int(args.delay)
        if args.status is not None:
            cfg["queryStatus"] = bool(args.status)
        if args.actual is not None:
            cfg["queryActualLevel"] = bool(args.actual)
        # Prefer POST (create-or-update); some firmwares 404 on PUT for a new line
        try:
            data = client.post_status_queries_line(args.line, cfg)
        except Exception:
            data = client.put_status_queries_line(args.line, cfg)
        Console().print(data)
        return 0
    sqs.set_defaults(func=_statusq_set)

    sqd = sqsp.add_parser("delete", help="Delete config for one line")
    sqd.add_argument("line", type=int)
    def _statusq_delete(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        data = client.delete_status_queries_line(args.line)
        Console().print(data if data else {"deleted": args.line})
        return 0
    sqd.set_defaults(func=_statusq_delete)

    # config: controller url, location and time
    cp = sub.add_parser("config", help="Controller configuration")
    csub = cp.add_subparsers(dest="section", required=True)

    # controller url store/show
    cu = csub.add_parser("controller", help="Controller base URL settings")
    cus = cu.add_subparsers(dest="action", required=True)

    cuset = cus.add_parser("set-url", help="Persist controller URL to config file")
    cuset.add_argument("url")
    def _cfg_set_url(args: argparse.Namespace) -> int:
        cfg = _load_config()
        if "controller" not in cfg or not isinstance(cfg.get("controller"), dict):
            cfg["controller"] = {}
        cfg["controller"]["url"] = str(args.url)
        _save_config(cfg)
        Console().print({"config": CONFIG_PATH, "url": cfg["controller"]["url"]})
        return 0
    cuset.set_defaults(func=_cfg_set_url)

    cuget = cus.add_parser("get-url", help="Show resolved controller URL and source")
    cuget.add_argument("--json", action="store_true")
    def _cfg_get_url(args: argparse.Namespace) -> int:
        url, source = _resolve_base_url(None)
        if args.json:
            json.dump({"url": url, "source": source, "config": CONFIG_PATH}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            Console().print({"url": url, "source": source, "config": CONFIG_PATH})
        return 0
    cuget.set_defaults(func=_cfg_get_url)

    # location
    lc = csub.add_parser("location", help="Get/set detected location")
    lsub = lc.add_subparsers(dest="action", required=True)

    lg = lsub.add_parser("get", help="Show current lat/lon")
    def _loc_get(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        json.dump(client.get_location(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    lg.set_defaults(func=_loc_get)

    ls = lsub.add_parser("set", help="Set lat/lon")
    ls.add_argument("--lat", type=float, required=True)
    ls.add_argument("--lon", type=float, required=True)
    def _loc_set(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        json.dump(client.set_location(args.lat, args.lon), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    ls.set_defaults(func=_loc_set)

    ld = lsub.add_parser("detect", help="Attempt to detect location from network")
    def _loc_detect(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        json.dump(client.detect_location(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    ld.set_defaults(func=_loc_detect)

    # time
    dt = csub.add_parser("time", help="Get/set time/timezone")
    dsub = dt.add_subparsers(dest="action", required=True)

    dtg = dsub.add_parser("get", help="Show datetime config")
    def _time_get(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        json.dump(client.get_datetime(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    dtg.set_defaults(func=_time_get)

    dts = dsub.add_parser("set", help="Set timezone and/or automatic time")
    dts.add_argument("--timezone")
    auto_grp = dts.add_mutually_exclusive_group()
    auto_grp.add_argument("--auto", dest="auto", action="store_true")
    auto_grp.add_argument("--no-auto", dest="auto", action="store_false")
    dts.set_defaults(auto=None)
    def _time_set(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        data = client.set_datetime(timezone=args.timezone, automatic_time=args.auto)
        json.dump(data, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    dts.set_defaults(func=_time_set)

    dttz = dsub.add_parser("timezones", help="List supported timezone names")
    def _time_timezones(args: argparse.Namespace) -> int:
        client = Client(base_url=args.url, timeout=args.timeout)
        tz = client.get_timezones()
        json.dump(tz, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    dttz.set_defaults(func=_time_timezones)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Resolve URL from arg > config > env > default
    resolved_url, _source = _resolve_base_url(getattr(args, "url", None))
    args.url = resolved_url
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
