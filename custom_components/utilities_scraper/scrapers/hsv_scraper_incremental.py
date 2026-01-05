import requests
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
import urllib.parse

BASE_URL = "https://hsvutil.org"

DEFAULT_ELECTRIC_INTERVAL = "HOURLY"
DEFAULT_GAS_INTERVAL = "HOURLY"
DEFAULT_WATER_INTERVAL = "MONTHLY"


def _load_json(path: str) -> dict:
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def _save_json(path: str, data: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


def load_token(token_file: str) -> str | None:
    p = Path(token_file)
    if p.exists():
        try:
            return json.loads(p.read_text()).get("access_token")
        except Exception:
            return None
    return None


def save_token(token_file: str, token: str) -> None:
    p = Path(token_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"access_token": token}))


def create_session(username: str, password: str, token_file: str) -> requests.Session | None:
    session = requests.Session()

    token = load_token(token_file)
    if token:
        session.headers.update({"Authorization": f"Bearer {token}"})
        try:
            response = session.get(f"{BASE_URL}/services/secured/accounts", params={"user": username})
            if response.status_code == 200:
                return session
        except Exception:
            pass

    response = session.post(
        f"{BASE_URL}/login",
        data={"username": username, "password": password},
        headers={"User-Agent": "Mozilla/5.0"},
        allow_redirects=True,
    )

    if not ("/ui/" in response.url or "dashboard" in response.url.lower()):
        return None

    try:
        response = session.get(response.url)
        if response.status_code == 200:
            token = session.cookies.get("access_token")
            if token:
                save_token(token_file, token)
                session.headers.update({"Authorization": f"Bearer {token}"})
                return session
    except Exception:
        pass

    return None


def get_account_info(session: requests.Session, username: str) -> dict | None:
    response = session.get(f"{BASE_URL}/services/secured/accounts", params={"user": username})
    if response.status_code != 200:
        return None
    return response.json()


def get_usage_data(
    session: requests.Session,
    account_id: str,
    commodity: str,
    interval: str,
    start_date: datetime,
    end_date: datetime,
) -> list:
    params = {
        "accountId": account_id,
        "commodity": commodity,
        "interval": interval,
        "startDate": start_date.strftime("%m/%d/%Y"),
        "endDate": end_date.strftime("%m/%d/%Y"),
    }

    url = f"{BASE_URL}/services/secured/usage"
    response = session.get(url, params=params)

    if response.status_code != 200:
        return []

    try:
        data = response.json()
        return data.get("usage", [])
    except Exception:
        return []


def merge_data(existing: dict, new_data: dict) -> tuple[dict, int]:
    added_count = 0

    for industry in ["electric", "gas", "water"]:
        if industry not in new_data:
            continue

        if industry not in existing:
            existing[industry] = new_data[industry]
            added_count += sum(len(v) for v in new_data[industry].values())
            continue

        for interval, readings in new_data[industry].items():
            if interval not in existing[industry]:
                existing[industry][interval] = readings
                added_count += len(readings)
                continue

            existing_timestamps = set(
                r.get("timestamp") for r in existing[industry][interval] if r.get("timestamp") is not None
            )

            for reading in readings:
                ts = reading.get("timestamp")
                if ts not in existing_timestamps:
                    existing[industry][interval].append(reading)
                    existing_timestamps.add(ts)
                    added_count += 1

            existing[industry][interval].sort(key=lambda x: x.get("timestamp", ""))

    return existing, added_count


def _compute_last_timestamps(data: dict) -> dict:
    last_timestamps = {}

    for industry in ["electric", "gas", "water"]:
        last_timestamps[industry] = {}
        if industry not in data:
            continue

        for interval, readings in data[industry].items():
            if readings:
                last_timestamps[industry][interval] = readings[-1].get("timestamp")

    return last_timestamps


def hsv_test_login(username: str, password: str) -> tuple[bool, str]:
    # Minimal, fast, no file writes
    # (token cache is not used in test mode intentionally)
    tmp_token_file = str(Path.cwd() / ".hsv_test_token.json")
    try:
        session = create_session(username, password, tmp_token_file)
        if not session:
            return False, "login failed"
        info = get_account_info(session, username)
        if not info:
            return False, "could not fetch account info"
        return True, "ok"
    except Exception as e:
        return False, str(e)
    finally:
        try:
            Path(tmp_token_file).unlink(missing_ok=True)
        except Exception:
            pass


def run_hsv_incremental(
    username: str,
    password: str,
    data_file: str,
    token_file: str,
    test_only: bool = False,
    electric_interval: str = DEFAULT_ELECTRIC_INTERVAL,
    gas_interval: str = DEFAULT_GAS_INTERVAL,
    water_interval: str = DEFAULT_WATER_INTERVAL,
) -> dict:
    start_ts = datetime.utcnow().isoformat()

    session = create_session(username, password, token_file)
    if not session:
        return {"ok": False, "detail": "authentication failed", "last_update": start_ts, "added": 0, "total": 0}

    info = get_account_info(session, username)
    if not info:
        return {"ok": False, "detail": "could not fetch account info", "last_update": start_ts, "added": 0, "total": 0}

    if test_only:
        return {"ok": True, "detail": "ok", "last_update": start_ts, "added": 0, "total": 0}

    account_id = None
    try:
        accounts = info.get("accounts", [])
        if accounts:
            account_id = accounts[0].get("accountId") or accounts[0].get("account_id")
    except Exception:
        account_id = None

    if not account_id:
        return {"ok": False, "detail": "no account id found", "last_update": start_ts, "added": 0, "total": 0}

    existing = _load_json(data_file) if Path(data_file).exists() else {}
    if not existing:
        existing = {"electric": {}, "gas": {}, "water": {}}

    last_timestamps = _compute_last_timestamps(existing)

    now = datetime.now()
    end_date = now
    overlap_days = 3

    intervals = {
        "electric": electric_interval,
        "gas": gas_interval,
        "water": water_interval,
    }

    new_payload = {"electric": {}, "gas": {}, "water": {}}

    total_added = 0

    for industry, interval in intervals.items():
        # compute start date
        last_ts = last_timestamps.get(industry, {}).get(interval)
        if last_ts:
            try:
                last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00")).replace(tzinfo=None)
                start_date = last_dt - timedelta(days=overlap_days)
            except Exception:
                start_date = now - timedelta(days=30)
        else:
            start_date = now - timedelta(days=30)

        commodity = industry.upper()

        readings = get_usage_data(session, account_id, commodity, interval, start_date, end_date)
        new_payload[industry][interval] = readings

        # be polite to the server
        time.sleep(0.25)

    merged, added = merge_data(existing, new_payload)
    total_added += added

    _save_json(data_file, merged)

    total = 0
    for industry in ["electric", "gas", "water"]:
        for interval, readings in merged.get(industry, {}).items():
            total += len(readings)

    return {
        "ok": True,
        "detail": "ok",
        "last_update": start_ts,
        "added": total_added,
        "total": total,
    }
