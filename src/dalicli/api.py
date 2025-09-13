from __future__ import annotations

import dataclasses
import time
from typing import Any, Dict, Iterable, List, Optional

import requests


@dataclasses.dataclass
class Client:
    base_url: str = "http://10.0.0.239"
    timeout: float = 5.0
    session: Optional[requests.Session] = None

    def _s(self) -> requests.Session:
        if self.session is None:
            self.session = requests.Session()
        return self.session

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    # --- Core endpoints ---
    def get_devices(self) -> Dict[str, Any]:
        r = self._s().get(self._url("/devices"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_device(self, device_id: int) -> Dict[str, Any]:
        r = self._s().get(self._url(f"/device/{device_id}"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def control_device(self, device_id: int, payload: Dict[str, Any]) -> None:
        r = self._s().post(self._url(f"/device/{device_id}/control"), json=payload, timeout=self.timeout)
        r.raise_for_status()

    def control_group(self, group_id: int, payload: Dict[str, Any], line: Optional[int] = None) -> None:
        params = {"_line": line} if line is not None else None
        r = self._s().post(self._url(f"/group/{group_id}/control"), params=params, json=payload, timeout=self.timeout)
        r.raise_for_status()

    def control_broadcast(self, payload: Dict[str, Any], line: Optional[int] = None) -> None:
        params = {"_line": line} if line is not None else None
        r = self._s().post(self._url("/broadcast/control"), params=params, json=payload, timeout=self.timeout)
        r.raise_for_status()

    def control_zone(self, zone_id: int, payload: Dict[str, Any]) -> None:
        r = self._s().post(self._url(f"/zone/{zone_id}/control"), json=payload, timeout=self.timeout)
        r.raise_for_status()

    def start_scan(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        r = self._s().post(self._url("/dali/scan"), json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json() if r.content else {}

    def get_scan(self) -> Dict[str, Any]:
        r = self._s().get(self._url("/dali/scan"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_scan_line(self, line: int) -> Dict[str, Any]:
        r = self._s().get(self._url(f"/dali/scan/{line}"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def cancel_scan(self) -> None:
        r = self._s().post(self._url("/dali/scan/cancel"), timeout=self.timeout)
        r.raise_for_status()

    def link_enable(self) -> None:
        r = self._s().post(self._url("/link/enable"), timeout=self.timeout)
        r.raise_for_status()

    def link_disable(self) -> None:
        r = self._s().post(self._url("/link/disable"), timeout=self.timeout)
        r.raise_for_status()

    # --- Zones ---
    def get_zones(self) -> Dict[str, Any]:
        r = self._s().get(self._url("/zones"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_zone(self, zone_id: int) -> Dict[str, Any]:
        r = self._s().get(self._url(f"/zone/{zone_id}"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # --- Scene discovery helpers ---
    def device_scene_numbers(self, device: Dict[str, Any]) -> list[int]:
        out: set[int] = set()
        scenes = device.get("scenes") or []
        for s in scenes:
            if isinstance(s, int):
                out.add(s)
            elif isinstance(s, dict):
                for key in ("id", "scene", "number"):
                    v = s.get(key)
                    if isinstance(v, int):
                        out.add(v)
                        break
        return sorted(out)

    def zone_scene_numbers(self, zone: Dict[str, Any]) -> list[int]:
        # Collect target devices either explicitly listed or via DALI group membership
        explicit_dev_ids: list[int] = []
        group_ids: list[int] = []
        is_broadcast = (str(zone.get("name") or "").strip().lower() == "broadcast")
        for t in zone.get("targets", []) or []:
            if not isinstance(t, dict):
                continue
            t_type = (t.get("type") or "").lower()
            t_id = t.get("id")
            if isinstance(t_id, int):
                if t_type in ("", "device", "default"):
                    explicit_dev_ids.append(t_id)
                elif t_type in ("group", "d16group", "dali_group", "dali-group"):
                    group_ids.append(t_id)
            if t_type in ("broadcast", "all"):
                is_broadcast = True

        # Resolve group members by scanning devices list and filtering by membership
        devices_index: dict[int, Dict[str, Any]] = {}
        try:
            root = self.get_devices()
            for d in root.get("devices", []):
                if isinstance(d.get("id"), int):
                    devices_index[int(d["id"])] = d
        except requests.RequestException:
            pass

        target_devs: dict[int, Dict[str, Any]] = {}
        # include explicit
        for did in explicit_dev_ids:
            # prefer detailed record
            try:
                d = self.get_device(did)
            except requests.RequestException:
                d = devices_index.get(did, {"id": did})
            target_devs[did] = d
        # include group members
        if group_ids or is_broadcast:
            for d in list(devices_index.values()):
                groups = d.get("groups") or []
                try:
                    if is_broadcast or any(int(g) in group_ids for g in groups):
                        # fetch detail for scenes if possible
                        did = int(d.get("id"))
                        if did not in target_devs:
                            try:
                                d = self.get_device(did)
                            except requests.RequestException:
                                pass
                            target_devs[did] = d
                except Exception:
                    continue

        numbers: set[int] = set()
        for d in target_devs.values():
            for n in self.device_scene_numbers(d):
                numbers.add(n)
        return sorted(numbers)

    def zone_members(self, zone: Dict[str, Any]) -> list[Dict[str, Any]]:
        # Determine member devices of a zone (explicit device targets or by group membership)
        explicit_dev_ids: list[int] = []
        group_ids: list[int] = []
        is_broadcast = (str(zone.get("name") or "").strip().lower() == "broadcast")
        for t in zone.get("targets", []) or []:
            if not isinstance(t, dict):
                continue
            t_type = (t.get("type") or "").lower()
            t_id = t.get("id")
            if isinstance(t_id, int):
                if t_type in ("", "device", "default"):
                    explicit_dev_ids.append(t_id)
                elif t_type in ("group", "d16group", "dali_group", "dali-group"):
                    group_ids.append(t_id)
            if t_type in ("broadcast", "all"):
                is_broadcast = True

        members: dict[int, Dict[str, Any]] = {}
        # Fetch devices list to resolve groups
        try:
            root = self.get_devices()
            for d in root.get("devices", []):
                did = d.get("id")
                if isinstance(did, int):
                    if did in explicit_dev_ids:
                        members[did] = d
                    elif group_ids or is_broadcast:
                        gs = d.get("groups") or []
                        try:
                            if is_broadcast or any(int(g) in group_ids for g in gs):
                                members[did] = d
                        except Exception:
                            pass
        except requests.RequestException:
            pass

        return sorted(members.values(), key=lambda x: (x.get("line", 0), x.get("address", 0), x.get("id", 0)))

    # --- Config: location and datetime ---
    def get_location(self) -> Dict[str, Any]:
        r = self._s().get(self._url("/location"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def set_location(self, lat: float, lon: float) -> Dict[str, Any]:
        r = self._s().post(self._url("/location"), json={"lat": lat, "lon": lon}, timeout=self.timeout)
        r.raise_for_status()
        return r.json() if r.content else {"lat": lat, "lon": lon}

    def detect_location(self) -> Dict[str, Any]:
        r = self._s().post(self._url("/location/detect"), timeout=self.timeout)
        r.raise_for_status()
        return r.json() if r.content else {}

    def get_datetime(self) -> Dict[str, Any]:
        r = self._s().get(self._url("/datetime"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def set_datetime(self, timezone: Optional[str] = None, automatic_time: Optional[bool] = None,
                     date: Optional[str] = None, time_str: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if timezone is not None:
            payload["timezone"] = timezone
        if automatic_time is not None:
            payload["automatic_time"] = automatic_time
        if date is not None:
            payload["date"] = date
        if time_str is not None:
            payload["time"] = time_str
        r = self._s().post(self._url("/datetime"), json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_timezones(self) -> List[str]:
        r = self._s().get(self._url("/datetime/timezones"), timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            return data.get("timezones", [])
        return data

    # --- Scheduler (automations) ---
    def list_schedules(self) -> List[Dict[str, Any]]:
        r = self._s().get(self._url("/automations/schedules"), timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        # AllScheduleResponse: {"schedulers": [SchedulerResponse, ...]}
        if isinstance(data, dict):
            items = data.get("schedulers")
            if isinstance(items, list):
                return items
        return data if isinstance(data, list) else []

    def create_schedule(self, model: Dict[str, Any]) -> Dict[str, Any]:
        r = self._s().post(self._url("/automations/scheduler"), json=model, timeout=self.timeout)
        r.raise_for_status()
        return r.json() if r.content else {}

    def get_schedule(self, sched_id: int) -> Dict[str, Any]:
        r = self._s().get(self._url(f"/automations/scheduler/{sched_id}"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def delete_schedule(self, sched_id: int) -> None:
        r = self._s().delete(self._url(f"/automations/scheduler/{sched_id}"), timeout=self.timeout)
        r.raise_for_status()

    def start_schedule(self, sched_id: int) -> None:
        r = self._s().post(self._url(f"/automations/scheduler/{sched_id}/start"), timeout=self.timeout)
        r.raise_for_status()

    def stop_schedule(self, sched_id: int) -> None:
        r = self._s().post(self._url(f"/automations/scheduler/{sched_id}/stop"), timeout=self.timeout)
        r.raise_for_status()

    # --- Sensors ---
    def get_sensors(self) -> Dict[str, Any]:
        r = self._s().get(self._url("/sensors"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # --- Automations: triggers & sequences ---
    def get_trigger_actions(self) -> List[Dict[str, Any]]:
        r = self._s().get(self._url("/automations/triggerActions"), timeout=self.timeout)
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError:
            return []
        # TriggerActionsModel: {"triggerActions": [...]} or raw array fallback
        if isinstance(data, dict):
            items = data.get("triggerActions")
            if isinstance(items, list):
                return items
        return data if isinstance(data, list) else []

    def get_trigger_action(self, trig_id: int) -> Dict[str, Any]:
        r = self._s().get(self._url(f"/automations/triggerAction/{trig_id}"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_sequences(self) -> List[Dict[str, Any]]:
        r = self._s().get(self._url("/automations/sequences"), timeout=self.timeout)
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError:
            return []
        # AllSequenceResponse: {"sequences": [...]}
        if isinstance(data, dict):
            items = data.get("sequences")
            if isinstance(items, list):
                return items
        return data if isinstance(data, list) else []

    def get_sequence(self, seq_id: int) -> Dict[str, Any]:
        r = self._s().get(self._url(f"/automations/sequence/{seq_id}"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def start_sequence(self, seq_id: int) -> None:
        r = self._s().post(self._url(f"/automations/sequence/{seq_id}/start"), timeout=self.timeout)
        r.raise_for_status()

    def stop_sequence(self, seq_id: int) -> None:
        r = self._s().post(self._url(f"/automations/sequence/{seq_id}/stop"), timeout=self.timeout)
        r.raise_for_status()

    def create_sequence(self, model: Dict[str, Any]) -> Dict[str, Any]:
        r = self._s().post(self._url("/automations/sequence"), json=model, timeout=self.timeout)
        r.raise_for_status()
        return r.json() if r.content else {}

    def update_sequence(self, seq_id: int, model: Dict[str, Any]) -> Dict[str, Any]:
        r = self._s().put(self._url(f"/automations/sequence/{seq_id}"), json=model, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def delete_sequence(self, seq_id: int) -> None:
        r = self._s().delete(self._url(f"/automations/sequence/{seq_id}"), timeout=self.timeout)
        r.raise_for_status()

    def delete_trigger_action(self, trig_id: int) -> None:
        r = self._s().delete(self._url(f"/automations/triggerAction/{trig_id}"), timeout=self.timeout)
        r.raise_for_status()

    def start_trigger_action(self, trig_id: int) -> None:
        r = self._s().post(self._url(f"/automations/triggerAction/{trig_id}/start"), timeout=self.timeout)
        r.raise_for_status()

    def stop_trigger_action(self, trig_id: int) -> None:
        r = self._s().post(self._url(f"/automations/triggerAction/{trig_id}/stop"), timeout=self.timeout)
        r.raise_for_status()

    def create_trigger_action(self, model: Dict[str, Any]) -> Dict[str, Any]:
        r = self._s().post(self._url("/automations/triggerAction"), json=model, timeout=self.timeout)
        r.raise_for_status()
        return r.json() if r.content else {}

    def update_trigger_action(self, trig_id: int, model: Dict[str, Any]) -> Dict[str, Any]:
        r = self._s().put(self._url(f"/automations/triggerAction/{trig_id}"), json=model, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_circadians(self) -> List[Dict[str, Any]]:
        r = self._s().get(self._url("/automations/circadians"), timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            items = data.get("circadians")
            if isinstance(items, list):
                return items
        return data if isinstance(data, list) else []

    def get_circadian(self, circ_id: int) -> Dict[str, Any]:
        r = self._s().get(self._url(f"/automations/circadian/{circ_id}"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def delete_circadian(self, circ_id: int) -> None:
        r = self._s().delete(self._url(f"/automations/circadian/{circ_id}"), timeout=self.timeout)
        r.raise_for_status()

    def start_circadian(self, circ_id: int) -> None:
        r = self._s().post(self._url(f"/automations/circadian/{circ_id}/start"), timeout=self.timeout)
        r.raise_for_status()

    def stop_circadian(self, circ_id: int) -> None:
        r = self._s().post(self._url(f"/automations/circadian/{circ_id}/stop"), timeout=self.timeout)
        r.raise_for_status()

    def create_circadian(self, model: Dict[str, Any]) -> Dict[str, Any]:
        r = self._s().post(self._url("/automations/circadian"), json=model, timeout=self.timeout)
        r.raise_for_status()
        return r.json() if r.content else {}

    def update_circadian(self, circ_id: int, model: Dict[str, Any]) -> Dict[str, Any]:
        r = self._s().put(self._url(f"/automations/circadian/{circ_id}"), json=model, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_status_queries(self) -> Dict[str, Any]:
        r = self._s().get(self._url("/automations/statusQueries"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_status_query_bounds(self) -> Dict[str, Any]:
        r = self._s().get(self._url("/automations/statusQueries/bounds"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_status_queries_line(self, line: int) -> Dict[str, Any]:
        r = self._s().get(self._url(f"/automations/statusQueries/{line}"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def put_status_queries_line(self, line: int, config: Dict[str, Any]) -> Dict[str, Any]:
        r = self._s().put(self._url(f"/automations/statusQueries/{line}"), json=config, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def post_status_queries_line(self, line: int, config: Dict[str, Any]) -> Dict[str, Any]:
        r = self._s().post(self._url(f"/automations/statusQueries/{line}"), json=config, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def delete_status_queries_line(self, line: int) -> Dict[str, Any]:
        r = self._s().delete(self._url(f"/automations/statusQueries/{line}"), timeout=self.timeout)
        r.raise_for_status()
        return r.json() if r.content else {}

    @staticmethod
    def summarize_trigger_source(src: Dict[str, Any]) -> str:
        t = src.get("type")
        if t in ("device", "group"):
            return f"{t}:{src.get('id')}"
        if t in ("d16gear", "d16group"):
            return f"{t}:line{src.get('line')}@{src.get('address')}"
        return str(src)

    @staticmethod
    def summarize_features(features: Dict[str, Any]) -> str:
        if not isinstance(features, dict):
            return "-"
        # Prefer scene if present, else dimmable/switchable, else list keys
        if "scene" in features:
            return f"scene:{features['scene']}"
        for k in ("dimmable", "switchable"):
            if k in features:
                return f"{k}:{features[k]}"
        return ",".join(sorted(features.keys())) or "-"

    # --- Utilities ---
    def poll_devices(self, ids: Optional[Iterable[int]] = None) -> List[Dict[str, Any]]:
        """Poll devices with optional explicit ids.

        - If ids is None, first fetch /devices and use those ids.
        - For each id, GET /device/{id} to confirm reachability and measure latency.
        - Returns a list of device dicts augmented with keys: latency_ms, reachable.
        """
        devices: List[Dict[str, Any]] = []
        if ids is None:
            root = self.get_devices()
            for d in root.get("devices", []):
                devices.append(d)
        else:
            for i in ids:
                devices.append({"id": int(i)})

        results: List[Dict[str, Any]] = []
        for d in devices:
            did = int(d.get("id"))
            t0 = time.perf_counter()
            ok = True
            detail: Dict[str, Any] = {}
            try:
                detail = self.get_device(did)
            except requests.RequestException:
                ok = False
            t1 = time.perf_counter()
            merged = {**d, **detail}
            merged["reachable"] = ok
            merged["latency_ms"] = round((t1 - t0) * 1000, 1)
            results.append(merged)
        # sort by line, address, id for readability if present
        results.sort(key=lambda x: (x.get("line", 0), x.get("address", 0), x.get("id", 0)))
        return results

    # --- Capability inference ---
    @staticmethod
    def classify_device(device: Dict[str, Any]) -> Dict[str, Any]:
        """Infer high-level capabilities from daliTypes and features.

        Returns keys: kind (relay|led|color|incandescent|unknown),
        supports_switch (bool), supports_dim (bool), supports_color (bool).
        """
        kinds = []
        supports_switch = False
        supports_dim = False
        supports_color = False

        types = device.get("daliTypes") or []
        tset = set(int(x) for x in types if isinstance(x, int))

        # Primary classification from DALI device types
        if 8 in tset:
            kinds.append("color")
            supports_color = True
            supports_dim = True
        if 6 in tset:
            kinds.append("led")
            supports_dim = True
        if 4 in tset:
            kinds.append("incandescent")
            supports_dim = True
        if 7 in tset:
            kinds.append("relay")
            supports_switch = True

        # Prefer most specific kind by priority
        priority = ["color", "led", "incandescent", "relay"]
        kind = next((k for k in priority if k in kinds), None)
        if kind is None:
            # Conservative fallback: do not infer color/dim from feature keys alone
            kind = "unknown"

        return {
            "kind": kind,
            "supports_switch": supports_switch,
            "supports_dim": supports_dim,
            "supports_color": supports_color,
        }
