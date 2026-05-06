import ssl
import uuid
import base64
import os
import string
import random
import json
import logging
import asyncio
import aiohttp
from datetime import datetime
from config import XUI_URL, XUI_LOGIN, XUI_PASSWORD, TRIAL_GB

logger = logging.getLogger(__name__)

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_session: aiohttp.ClientSession | None = None
_login_lock = asyncio.Lock()
_last_login: float = 0.0
SESSION_TTL = 25 * 60


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(ssl=_SSL_CTX, limit=10, ttl_dns_cache=300)
        jar = aiohttp.CookieJar(unsafe=True)
        _session = aiohttp.ClientSession(connector=connector, cookie_jar=jar)
    return _session


async def login() -> bool:
    global _last_login
    async with _login_lock:
        import time
        now = time.monotonic()
        if now - _last_login < 5:
            return True
        session = await _get_session()
        try:
            async with session.post(
                f"{XUI_URL}/login",
                data={"username": XUI_LOGIN, "password": XUI_PASSWORD},
                ssl=_SSL_CTX,
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=True,
            ) as resp:
                text = await resp.text()
                try:
                    data = json.loads(text)
                except Exception:
                    logger.error(f"x-ui login non-JSON: {text[:200]}")
                    return False
                if data.get("success"):
                    _last_login = now
                    logger.info("x-ui login successful")
                    return True
                logger.error(f"x-ui login failed: {data}")
                return False
        except Exception as e:
            logger.error(f"x-ui login error: {e}")
            return False


async def _ensure_fresh_session():
    import time
    if time.monotonic() - _last_login > SESSION_TTL:
        await login()


async def _request(method: str, path: str, retry: bool = True, **kwargs) -> dict | None:
    await _ensure_fresh_session()
    session = await _get_session()
    url = f"{XUI_URL}{path}"
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with session.request(
            method, url, ssl=_SSL_CTX, timeout=timeout, allow_redirects=True, **kwargs
        ) as resp:
            if resp.status in (401, 403):
                if retry:
                    await login()
                    return await _request(method, path, retry=False, **kwargs)
                return None
            if resp.status == 404:
                logger.warning(f"404 on {method} {path}")
                return None
            text = await resp.text()
            try:
                data = json.loads(text)
            except Exception:
                if retry and "login" in text.lower():
                    await login()
                    return await _request(method, path, retry=False, **kwargs)
                logger.error(f"Non-JSON on {method} {path}: {text[:200]}")
                return None
            if isinstance(data, dict) and not data.get("success") and retry:
                msg = str(data.get("msg", "")).lower()
                if any(k in msg for k in ("login", "auth", "session", "unauthorized")):
                    await login()
                    return await _request(method, path, retry=False, **kwargs)
            return data
    except asyncio.TimeoutError:
        logger.error(f"Timeout on {method} {path}")
        return None
    except Exception as e:
        logger.error(f"x-ui request error [{method} {path}]: {e}")
        if retry:
            await login()
            return await _request(method, path, retry=False, **kwargs)
        return None


_INBOUNDS_PATHS = [
    "/panel/api/inbounds/list",
    "/xui/API/inbounds",
    "/xui/inbound/list",
]
_working_inbounds_path: str | None = None


async def get_inbounds() -> list[dict]:
    global _working_inbounds_path
    paths = [_working_inbounds_path] if _working_inbounds_path else _INBOUNDS_PATHS
    for path in paths:
        data = await _request("GET", path)
        if data and data.get("success"):
            if not _working_inbounds_path:
                logger.info(f"x-ui inbounds path found: {path}")
                _working_inbounds_path = path
            return data.get("obj", [])
    if _working_inbounds_path:
        _working_inbounds_path = None
    logger.error("No working inbounds path found")
    return []


async def _get_inbound_full(inbound_id: int) -> dict | None:
    """Fetch a single inbound with FULL settings (all clients)."""
    data = await _request("GET", f"/panel/api/inbounds/get/{inbound_id}")
    if data and data.get("success") and data.get("obj"):
        return data["obj"]
    return None


def _rand_ss_password() -> str:
    """16-byte key as standard base64 WITH padding — required by shadowsocks_2022."""
    return base64.b64encode(os.urandom(16)).decode()  # e.g. "KIpZdve7dPIb9rfH99DT4w=="


def _rand_auth(n: int = 10) -> str:
    """Random alphanumeric auth string for Hysteria2."""
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=n))


def _build_new_client(protocol: str, inbound: dict, tg_id: int, email: str,
                       sub_id: str, expiry_ms: int, total_bytes: int) -> dict:
    """Build a brand-new client object for the given protocol."""
    base = {
        "email": email,
        "subId": sub_id,
        "expiryTime": expiry_ms,
        "totalGB": total_bytes,
        "enable": True,
        "limitIp": 0,
        "tgId": str(tg_id),
        "reset": 0,
        "comment": "",
    }
    if protocol == "shadowsocks":
        base["password"] = _rand_ss_password()
        base["method"] = ""
        return base
    elif protocol in ("hysteria", "hysteria2"):
        base["auth"] = _rand_auth(10)
        return base
    else:
        base["id"] = str(uuid.uuid4())
        base["flow"] = ""
        return base


def _find_client_in_settings(inbound: dict, email: str) -> dict | None:
    """Search inbound settings JSON for a client with the given email."""
    try:
        settings = inbound.get("settings")
        if isinstance(settings, str):
            settings = json.loads(settings)
        for client in (settings or {}).get("clients", []):
            if client.get("email") == email:
                return dict(client)
    except Exception:
        pass
    return None


def _calc_expiry_ms(days: int, extend: bool, current_expiry_ms: int | None) -> int:
    now_ms = int(datetime.utcnow().timestamp() * 1000)
    if extend and current_expiry_ms and current_expiry_ms > now_ms:
        base_ms = current_expiry_ms
    else:
        base_ms = now_ms
    return base_ms + days * 24 * 3600 * 1000


_ADD_PATHS = [
    "/panel/api/inbounds/addClient",
    "/xui/API/inbounds/addClient",
]

_UPDATE_PATHS = [
    "/panel/api/inbounds/updateClient/{key}",
    "/xui/API/inbounds/updateClient/{key}",
]


async def _do_add_client(inbound_id: int, client: dict) -> tuple[bool, str]:
    """Try all add paths. Returns (success, error_msg)."""
    payload = {"id": inbound_id, "settings": json.dumps({"clients": [client]})}
    last_msg = ""
    for path in _ADD_PATHS:
        data = await _request("POST", path, json=payload)
        if data and data.get("success"):
            return True, ""
        if data is not None:
            last_msg = data.get("msg", "") or ""
    return False, last_msg


async def _do_update_client(inbound_id: int, client: dict, protocol: str) -> bool:
    """Try all update paths using protocol-specific key."""
    if protocol in ("hysteria", "hysteria2"):
        key = client.get("auth", client.get("email", ""))
    elif protocol == "shadowsocks":
        key = client.get("email", "")
    else:
        key = client.get("id", "")

    client_copy = dict(client)
    payload = {"id": inbound_id, "settings": json.dumps({"clients": [client_copy]})}
    for tpl in _UPDATE_PATHS:
        path = tpl.format(key=key)
        data = await _request("POST", path, json=payload)
        if data and data.get("success"):
            return True
        if data is not None:
            logger.debug(f"updateClient {path}: {data.get('msg', data)}")
    return False


async def _add_or_update_client(
    inbound: dict, protocol: str, tg_id: int, email: str,
    sub_id: str, expiry_ms: int, total_bytes: int,
) -> bool:
    inbound_id = inbound["id"]

    # 1. Quick check: client in settings from list response
    existing = _find_client_in_settings(inbound, email)

    if existing:
        existing["expiryTime"] = expiry_ms
        existing["totalGB"] = total_bytes
        existing["enable"] = True
        existing["subId"] = sub_id
        return await _do_update_client(inbound_id, existing, protocol)

    # 2. Try to add as new
    new_client = _build_new_client(protocol, inbound, tg_id, email, sub_id, expiry_ms, total_bytes)
    ok, err = await _do_add_client(inbound_id, new_client)
    if ok:
        return True

    # 3. If "Duplicate email", the client exists but wasn't in the list response.
    #    Fetch the full inbound separately to find and update it.
    if "duplicate" in err.lower() or "email" in err.lower():
        logger.info(f"Duplicate email on inbound {inbound_id}, fetching full inbound to update...")
        full_inbound = await _get_inbound_full(inbound_id)
        if full_inbound:
            existing = _find_client_in_settings(full_inbound, email)
            if existing:
                existing["expiryTime"] = expiry_ms
                existing["totalGB"] = total_bytes
                existing["enable"] = True
                existing["subId"] = sub_id
                ok = await _do_update_client(inbound_id, existing, protocol)
                if ok:
                    return True
        # Last resort: force-update with a new payload using email as key
        new_client["expiryTime"] = expiry_ms
        return await _do_update_client(inbound_id, new_client, protocol)

    logger.warning(f"addClient inbound={inbound_id} ({protocol}) failed: {err}")
    return False


async def add_client_to_all_inbounds(
    tg_id: int,
    sub_id: str,
    days: int,
    is_trial: bool = False,
    extend: bool = False,
    current_expiry_ms: int | None = None,
) -> bool:
    inbounds = await get_inbounds()
    if not inbounds:
        logger.error("No inbounds found")
        return False

    expiry_ms = _calc_expiry_ms(days, extend, current_expiry_ms)
    total_bytes = TRIAL_GB * 1024 ** 3 if is_trial else 0
    email = str(tg_id)

    results = await asyncio.gather(*[
        _add_or_update_client(
            inbound=ib,
            protocol=ib.get("protocol", "vless"),
            tg_id=tg_id,
            email=email,
            sub_id=sub_id,
            expiry_ms=expiry_ms,
            total_bytes=total_bytes,
        )
        for ib in inbounds
    ])

    success = sum(1 for r in results if r)
    logger.info(f"User {tg_id}: {success}/{len(inbounds)} inbounds OK")
    return success > 0


async def get_expiry_for_user(tg_id: int) -> int | None:
    email = str(tg_id)
    inbounds = await get_inbounds()
    for ib in inbounds:
        client = _find_client_in_settings(ib, email)
        if client:
            return client.get("expiryTime")
        # Also check clientStats
        for stat in (ib.get("clientStats") or []):
            if stat.get("email") == email:
                return None  # stats don't have expiry, need full inbound
    # Try fetching first inbound fully
    if inbounds:
        full = await _get_inbound_full(inbounds[0]["id"])
        if full:
            client = _find_client_in_settings(full, email)
            if client:
                return client.get("expiryTime")
    return None


def fmt_bytes(b: int | float) -> str:
    b = float(b)
    if b == 0:
        return "0 Б"
    for unit in ["Б", "КБ", "МБ", "ГБ", "ТБ"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} ТБ"
