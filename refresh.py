#!/usr/bin/env python3
"""Fetch Cursor billing into snapshot.js. Stdlib only."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

DIR = Path(__file__).resolve().parent
SNAPSHOT_PATH = DIR / "snapshot.js"
BASE = "https://api2.cursor.sh"
AUTH_PROFILE = f"{BASE}/auth/full_stripe_profile"
DASH = f"{BASE}/aiserver.v1.DashboardService"
USAGE = f"{DASH}/GetCurrentPeriodUsage"
PLAN = f"{DASH}/GetPlanInfo"
EVENTS = f"{DASH}/GetFilteredUsageEvents"

KIND_ON_DEMAND = "USAGE_EVENT_KIND_USAGE_BASED"
KIND_INCLUDED = "USAGE_EVENT_KIND_INCLUDED_IN_BUSINESS"
MAX_PAGES = 20


def empty_snapshot(error: str | None = None) -> dict[str, Any]:
    return {
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "error": error,
        "cycle": None,
        "plan": None,
        "pools": None,
        "spend": None,
        "team": None,
        "status": "",
        "onDemand": [],
        "uses": [],
        "models": [],
    }


def vscdb_candidates() -> list[Path]:
    home = Path.home()
    if override := os.environ.get("CURSOR_VSCDB"):
        return [Path(override)]
    if sys.platform == "darwin":
        return [
            home / "Library/Application Support/Cursor/User/globalStorage/state.vscdb",
            home
            / "Library/Application Support/Cursor - Insiders/User/globalStorage/state.vscdb",
        ]
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", home / "AppData/Roaming"))
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        return [
            appdata / "Cursor/User/globalStorage/state.vscdb",
            appdata / "Cursor - Insiders/User/globalStorage/state.vscdb",
            local / "Cursor/User/globalStorage/state.vscdb",
        ]
    return [
        home / ".config/Cursor/User/globalStorage/state.vscdb",
        home / ".config/cursor/User/globalStorage/state.vscdb",
    ]


def find_vscdb() -> Path:
    for path in vscdb_candidates():
        if path.is_file():
            return path
    tried = "\n".join(f"  - {p}" for p in vscdb_candidates())
    raise RuntimeError(f"state.vscdb not found. Tried:\n{tried}")


def read_token() -> str:
    vscdb = find_vscdb()
    uri = f"file:{vscdb.as_posix()}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    try:
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key = ?",
            ("cursorAuth/accessToken",),
        ).fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        raise RuntimeError(f"cursorAuth/accessToken missing in {vscdb}")
    return str(row[0])


def api_json(
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["connect-protocol-version"] = "1"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def ms_to_iso(ms: int | str | None) -> str | None:
    if ms is None or ms == "":
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()


def parse_seat_usd(price: str | None) -> float:
    if not price:
        return 0.0
    m = re.search(r"[\d.]+", price)
    return float(m.group(0)) if m else 0.0


def cents(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    return float(v) / 100.0


def load_snapshot_file() -> dict[str, Any]:
    raw = SNAPSHOT_PATH.read_text(encoding="utf-8")
    json_part = raw.split("=", 1)[1].strip()
    if json_part.endswith(";"):
        json_part = json_part[:-1]
    return json.loads(json_part)


def write_snapshot(snap: dict[str, Any]) -> None:
    text = "window.SNAPSHOT = " + json.dumps(snap, ensure_ascii=False, indent=2) + ";\n"
    SNAPSHOT_PATH.write_text(text, encoding="utf-8")


def build_snapshot(token: str) -> dict[str, Any]:
    profile = api_json("GET", AUTH_PROFILE, token)
    team_id = profile.get("teamId")
    if team_id is None:
        raise RuntimeError("teamId missing from full_stripe_profile")
    team_id = int(team_id)

    usage = api_json("POST", USAGE, token, {})
    plan_info = api_json("POST", PLAN, token, {})
    plan_usage = usage.get("planUsage") or {}
    spend_limit = usage.get("spendLimitUsage") or {}
    plan_block = plan_info.get("planInfo") or plan_info

    events: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        payload = api_json(
            "POST",
            EVENTS,
            token,
            {"teamId": team_id, "pageSize": 100, "page": page},
        )
        batch = payload.get("usageEventsDisplay") or []
        if not isinstance(batch, list):
            batch = []
        events.extend(batch)
        if len(batch) < 100:
            break

    start_ms = usage.get("billingCycleStart")
    end_ms = usage.get("billingCycleEnd")
    start_i = int(start_ms) if start_ms not in (None, "") else None
    end_i = int(end_ms) if end_ms not in (None, "") else None

    auto_bucket = set(usage.get("autoBucketModels") or [])
    # autoBucketModels lags new first-party ids (grok-4.7 was missing on 2026-09-25).
    cursor_prefixes = ("grok-", "composer-", "cursor-", "vega")

    def pool_of(name: str) -> str:
        if name in auto_bucket or name == "default":
            return "cursor"
        if name.startswith(cursor_prefixes):
            return "cursor"
        return "other"

    on_demand: list[dict[str, Any]] = []
    uses: list[dict[str, Any]] = []
    models: dict[str, dict[str, Any]] = {}

    def ensure_model(name: str) -> dict[str, Any]:
        if name not in models:
            models[name] = {
                "model": name,
                "pool": pool_of(name),
                "includedUsd": 0.0,
                "onDemandUsd": 0.0,
                "calls": 0,
            }
        return models[name]

    for ev in events:
        kind = ev.get("kind") or ""
        # Aborted / errored kinds are not included or usage-based
        if kind not in (KIND_ON_DEMAND, KIND_INCLUDED):
            continue

        ts = ev.get("timestamp")
        if ts is None:
            continue
        ts_i = int(ts)
        if start_i is not None and ts_i < start_i:
            continue
        if end_i is not None and ts_i >= end_i:
            continue

        model = str(ev.get("model") or "unknown")
        m = ensure_model(model)
        m["calls"] += 1
        usd = round(cents(ev.get("chargedCents") or 0), 4)
        on_demand_kind = kind == KIND_ON_DEMAND

        if on_demand_kind:
            m["onDemandUsd"] += usd
            on_demand.append(
                {"at": ms_to_iso(ts_i), "model": model, "usd": usd}
            )
        else:
            m["includedUsd"] += usd

        uses.append(
            {
                "at": ms_to_iso(ts_i),
                "model": model,
                "pool": m["pool"],
                "usd": usd,
                "onDemand": on_demand_kind,
            }
        )

    on_demand.sort(key=lambda x: x["at"] or "", reverse=True)
    uses.sort(key=lambda x: x["at"] or "", reverse=True)
    model_list = sorted(
        models.values(),
        key=lambda x: x["includedUsd"] + x["onDemandUsd"],
        reverse=True,
    )
    for m in model_list:
        m["includedUsd"] = round(m["includedUsd"], 4)
        m["onDemandUsd"] = round(m["onDemandUsd"], 4)

    on_demand_usd = round(sum(x["usd"] for x in on_demand), 4)
    status = (
        usage.get("namedModelSelectedDisplayMessage")
        or usage.get("displayMessage")
        or ""
    )

    return {
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "error": None,
        "cycle": {
            "start": ms_to_iso(start_i),
            "end": ms_to_iso(end_i),
        },
        "plan": {
            "name": str(plan_block.get("planName") or ""),
            "seatUsd": parse_seat_usd(plan_block.get("price")),
            "includedApiUsd": cents(plan_block.get("includedAmountCents") or 0),
        },
        "pools": {
            "cursor": {"percentUsed": float(plan_usage.get("autoPercentUsed") or 0)},
            "other": {"percentUsed": float(plan_usage.get("apiPercentUsed") or 0)},
        },
        "spend": {
            "includedUsd": cents(plan_usage.get("includedSpend") or 0),
            "bonusUsd": cents(plan_usage.get("bonusSpend") or 0),
            "onDemandUsd": on_demand_usd,
            "meterUsd": cents(spend_limit.get("individualUsed") or 0),
        },
        "team": {
            "onDemandUsd": cents(spend_limit.get("pooledUsed") or 0),
            "limitUsd": cents(spend_limit.get("pooledLimit") or 0),
        },
        "status": str(status),
        "onDemand": on_demand,
        "uses": uses,
        "models": model_list,
    }


def refresh() -> dict[str, Any]:
    try:
        token = read_token()
        snap = build_snapshot(token)
        write_snapshot(snap)
        return snap
    except Exception as e:
        snap = empty_snapshot(str(e))
        write_snapshot(snap)
        raise


def print_summary(snap: dict[str, Any]) -> None:
    od = (snap.get("spend") or {}).get("onDemandUsd")
    if od is None:
        od = 0
    print(od)
    print(SNAPSHOT_PATH)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/refresh":
            try:
                snap = refresh()
                code = 200
            except Exception:
                snap = load_snapshot_file()
                code = 500
            body = json.dumps(snap, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        path = self.path.split("?", 1)[0]
        if path == "/":
            path = "/index.html"
        target = (DIR / path.lstrip("/")).resolve()
        try:
            target.relative_to(DIR)
        except ValueError:
            self.send_error(404)
            return
        if not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        ctype = "application/octet-stream"
        if target.suffix == ".html":
            ctype = "text/html; charset=utf-8"
        elif target.suffix == ".js":
            ctype = "application/javascript; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve() -> None:
    httpd = HTTPServer(("127.0.0.1", 8765), Handler)
    print("http://127.0.0.1:8765/", file=sys.stderr)
    httpd.serve_forever()


def main() -> int:
    serve_mode = "--serve" in sys.argv
    try:
        snap = refresh()
        print_summary(snap)
        if serve_mode:
            serve()
        return 0
    except Exception:
        try:
            snap = load_snapshot_file()
        except Exception:
            snap = empty_snapshot("refresh failed")
        print_summary(snap)
        if serve_mode:
            serve()
        return 1


if __name__ == "__main__":
    sys.exit(main())
