import requests
import json
from datetime import datetime, timedelta
import time
from pathlib import Path
from playwright.sync_api import sync_playwright


ECOBEE_API_BASE = "https://api.ecobee.com/1"


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


def extract_access_token(
    username: str,
    password: str,
    two_fa_code: str,
    session_file: str,
    headless: bool = True,
) -> str:
    token_holder = {"token": None}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=session_file if Path(session_file).exists() else None)
        page = context.new_page()

        def handle_response(response):
            try:
                url = response.url
                if "authCallback" in url or "authorize" in url:
                    body = response.request.post_data
                    if body and "access_token=" in body:
                        token_holder["token"] = body.split("access_token=")[1].split("&")[0]
            except Exception:
                pass

        page.on("response", handle_response)

        page.goto("https://www.ecobee.com")
        page.click("text=Sign In", timeout=15000)

        page.wait_for_selector('input[name="username"]', timeout=15000)
        page.fill('input[name="username"]', username)
        page.click('button[type="submit"]')

        page.wait_for_selector('input[name="password"]', timeout=15000)
        page.fill('input[name="password"]', password)
        page.click('button[type="submit"]')

        # 2FA code must be provided by user (no TOTP secret, no interactive prompt)
        page.wait_for_selector('input[name="code"]', timeout=20000)
        page.fill('input[name="code"]', two_fa_code)
        page.click('button[type="submit"]')

        page.wait_for_url("**/consumerportal/**", timeout=30000)

        context.storage_state(path=session_file)

        token = token_holder["token"]

        if not token:
            token = page.evaluate(
                """
                () => localStorage.getItem('access_token') ||
                     sessionStorage.getItem('access_token')
                """
            )

        if not token:
            # last resort: look for token-ish cookies
            cookies = context.cookies()
            for cookie in cookies:
                if "token" in cookie["name"].lower():
                    token = cookie["value"]
                    break

        browser.close()

        if not token:
            raise RuntimeError("could not extract access token")

        return token


def get_thermostat_id(access_token: str) -> str:
    url = f"{ECOBEE_API_BASE}/user"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    thermostat_list = data.get("user", {}).get("thermostatList", [])
    if not thermostat_list:
        raise RuntimeError("no thermostat id found")
    return thermostat_list[0]


def fetch_runtime_report(
    access_token: str,
    thermostat_id: str,
    start_date: datetime,
    end_date: datetime,
) -> list[dict]:
    url = f"{ECOBEE_API_BASE}/runtimeReport"
    headers = {"Authorization": f"Bearer {access_token}"}

    selection = {
        "selectionType": "thermostats",
        "selectionMatch": thermostat_id,
        "includeRuntime": True,
    }

    params = {
        "format": "json",
        "body": json.dumps(
            {
                "startDate": start_date.strftime("%Y-%m-%d"),
                "endDate": end_date.strftime("%Y-%m-%d"),
                "selection": selection,
            }
        ),
    }

    resp = requests.get(url, headers=headers, params=params, timeout=60)
    resp.raise_for_status()
    payload = resp.json()

    reports = payload.get("reportList", [])
    if not reports:
        return []

    # each report has a rowList where each row corresponds to a timestamp interval
    # we keep them in a normalized format similar to your original approach
    normalized = []
    for report in reports:
        row_list = report.get("rowList", [])
        columns = report.get("columns", "")
        col_names = columns.split(",") if columns else []
        for row in row_list:
            parts = row.split(",")
            if len(parts) < 2:
                continue
            # first column is usually date/time
            entry = {"raw": row, "columns": col_names}
            # best-effort timestamp extraction: parts[0] is date, parts[1] might be time
            entry["date"] = parts[0]
            if len(parts) > 1:
                entry["time"] = parts[1]
            normalized.append(entry)

    return normalized


def merge_data(existing: dict, new_rows: list[dict]) -> tuple[dict, int]:
    if "readings" not in existing:
        existing["readings"] = []

    existing_keys = set()
    for r in existing["readings"]:
        k = (r.get("date"), r.get("time"), r.get("raw"))
        existing_keys.add(k)

    added = 0
    for r in new_rows:
        k = (r.get("date"), r.get("time"), r.get("raw"))
        if k not in existing_keys:
            existing["readings"].append(r)
            existing_keys.add(k)
            added += 1

    # sort by date/time (best effort)
    existing["readings"].sort(key=lambda x: (x.get("date", ""), x.get("time", ""), x.get("raw", "")))
    return existing, added


def ecobee_test_login(username: str, password: str, two_fa_code: str) -> tuple[bool, str]:
    tmp_session = str(Path.cwd() / ".ecobee_test_session.json")
    tmp_token = str(Path.cwd() / ".ecobee_test_token.json")

    try:
        token = extract_access_token(username, password, two_fa_code, tmp_session, headless=True)
        thermostat_id = get_thermostat_id(token)
        if thermostat_id:
            return True, "ok"
        return False, "no thermostat id"
    except Exception as e:
        return False, str(e)
    finally:
        try:
            Path(tmp_session).unlink(missing_ok=True)
        except Exception:
            pass
        try:
            Path(tmp_token).unlink(missing_ok=True)
        except Exception:
            pass


def run_ecobee_incremental(
    username: str,
    password: str,
    two_fa_code: str,
    data_file: str,
    session_file: str,
    token_file: str,
    headless: bool = True,
    test_only: bool = False,
) -> dict:
    start_ts = datetime.utcnow().isoformat()

    token = load_token(token_file)
    if token:
        try:
            # validate token quickly
            _ = get_thermostat_id(token)
        except Exception:
            token = None

    if not token:
        token = extract_access_token(username, password, two_fa_code, session_file, headless=headless)
        save_token(token_file, token)

    thermostat_id = get_thermostat_id(token)

    if test_only:
        return {"ok": True, "detail": "ok", "last_update": start_ts, "added": 0, "total": 0}

    existing = _load_json(data_file) if Path(data_file).exists() else {}
    if not existing:
        existing = {"readings": []}

    # Determine range:
    # - If we have existing data, pull last 2 days (overlap)
    # - Else pull last 7 days
    overlap_days = 2
    if existing.get("readings"):
        # best-effort: use last date present
        last = existing["readings"][-1]
        try:
            last_date = datetime.strptime(last.get("date", ""), "%Y-%m-%d")
            start_date = last_date - timedelta(days=overlap_days)
        except Exception:
            start_date = datetime.now() - timedelta(days=7)
    else:
        start_date = datetime.now() - timedelta(days=7)

    end_date = datetime.now()

    new_rows = fetch_runtime_report(token, thermostat_id, start_date, end_date)
    merged, added = merge_data(existing, new_rows)
    _save_json(data_file, merged)

    total = len(merged.get("readings", []))

    return {
        "ok": True,
        "detail": "ok",
        "last_update": start_ts,
        "added": added,
        "total": total,
    }
