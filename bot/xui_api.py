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
    return base64.b64encode(os.urandom(16)).decode()


def _rand_auth(n: int = 10) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=n))


def _get_ss_method(inbound: dict) -> str:
    """Extract shadowsocks method from inbound settings."""
    try:
        settings = inbound.get("settings")
        if isinstance(settings, str):
            settings = json.loads(settings)
        method = (settings or {}).get("method", "")
        if method:
            return method
    except Exception:
        pass
    return "aes-256-gcm"


def _uses_xtls(inbound: dict) -> bool:
    """Check if inbound uses XTLS security (flow field required)."""
    try:
        stream = inbound.get("streamSettings")
        if isinstance(stream, str):
            stream = json.loads(stream)
        return (stream or {}).get("security", "") == "xtls"
    except Exception:
        return False


def _make_email(tg_id: int, inbound_id: int) -> str:
    """
    Use per-inbound email: {tg_id}_{inbound_id}.
    x-ui validates email uniqueness GLOBALLY across all inbounds,
    so using just str(tg_id) causes 'Duplicate email' after the first inbound.
    Per-inbound emails + shared subId = all servers in one subscription link.
    """
    return f"{tg_id}_{inbound_id}"


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
        base["method"] = _get_ss_method(inbound)
        return base
    elif protocol in ("hysteria", "hysteria2"):
        base["auth"] = _rand_auth(10)
        return base
    else:
        base["id"] = str(uuid.uuid4())
        # Only set flow for XTLS — empty string causes N/A in v2rayTun
        if _uses_xtls(inbound):
            base["flow"] = "xtls-rprx-vision"
        return base


def _find_client_in_settings(inbound: dict, *emails: str) -> dict | None:
    """Search inbound settings JSON for a client matching any of the given emails."""
    try:
        settings = inbound.get("settings")
        if isinstance(settings, str):
            settings = json.loads(settings)
        email_set = set(emails)
        for client in (settings or {}).get("clients", []):
            if client.get("email") in email_set:
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


_ADD_PATH = "/panel/api/inbounds/addClient"
_UPDATE_PATH = "/panel/api/inbounds/updateClient/{key}"


async def _do_add_client(inbound_id: int, client: dict) -> tuple[bool, str]:
    """Add a new client. Returns (success, error_msg)."""
    payload = {"id": inbound_id, "settings": json.dumps({"clients": [client]})}
    data = await _request("POST", _ADD_PATH, json=payload)
    if data and data.get("success"):
        return True, ""
    msg = (data.get("msg", "") or "") if data else ""
    return False, msg


async def _do_update_client(inbound_id: int, client: dict, protocol: str) -> bool:
    """Update an existing client using protocol-specific key."""
    if protocol in ("hysteria", "hysteria2"):
        key = client.get("auth", client.get("email", ""))
    elif protocol == "shadowsocks":
        key = client.get("email", "")
    else:
        key = client.get("id", "")

    if not key:
        logger.warning(f"updateClient: empty key for protocol={protocol}")
        return False

    # Strip x-ui internal fields that can cause rejection
    client_copy = {k: v for k, v in client.items()
                   if k not in ("created_at", "updated_at")}

    payload = {"id": inbound_id, "settings": json.dumps({"clients": [client_copy]})}
    path = _UPDATE_PATH.format(key=key)
    data = await _request("POST", path, json=payload)
    if data and data.get("success"):
        return True
    logger.debug(f"updateClient {path}: {data.get('msg', data) if data else 'no response'}")
    return False


async def _add_or_update_client(
    inbound: dict, protocol: str, tg_id: int,
    sub_id: str, expiry_ms: int, total_bytes: int,
) -> bool:
    inbound_id = inbound["id"]
    # Primary email is per-inbound to avoid x-ui global duplicate constraint
    email = _make_email(tg_id, inbound_id)
    # Also search for the old-style global email in case client was added before
    old_email = str(tg_id)

    # 1. Search list response settings (fast path)
    existing = _find_client_in_settings(inbound, email, old_email)

    if existing:
        existing["expiryTime"] = expiry_ms
        existing["totalGB"] = total_bytes
        existing["enable"] = True
        existing["subId"] = sub_id
        existing["email"] = email  # normalize to new format
        if not _uses_xtls(inbound):
            existing.pop("flow", None)  # remove empty flow → fixes N/A
        return await _do_update_client(inbound_id, existing, protocol)

    # 2. Try to add as new client
    new_client = _build_new_client(protocol, inbound, tg_id, email, sub_id, expiry_ms, total_bytes)
    ok, err = await _do_add_client(inbound_id, new_client)
    if ok:
        return True

    # 3. Duplicate email — client exists but not in list response (large inbound).
    #    Fetch the full inbound to find and update it.
    if "duplicate" in err.lower() or "email" in err.lower() or "exist" in err.lower():
        logger.info(f"Inbound {inbound_id}: duplicate email, fetching full inbound...")
        full_inbound = await _get_inbound_full(inbound_id)
        if full_inbound:
            existing = _find_client_in_settings(full_inbound, email, old_email)
            if existing:
                existing["expiryTime"] = expiry_ms
                existing["totalGB"] = total_bytes
                existing["enable"] = True
                existing["subId"] = sub_id
                existing["email"] = email  # normalize email
                if not _uses_xtls(inbound):
                    existing.pop("flow", None)
                ok = await _do_update_client(inbound_id, existing, protocol)
                if ok:
                    return True

    logger.warning(f"add_or_update inbound={inbound_id} ({protocol}) email={email} failed: {err}")
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

    # Process SEQUENTIALLY — x-ui uses SQLite; concurrent writes cause failures
    success_count = 0
    for ib in inbounds:
        try:
            ok = await _add_or_update_client(
                inbound=ib,
                protocol=ib.get("protocol", "vless"),
                tg_id=tg_id,
                sub_id=sub_id,
                expiry_ms=expiry_ms,
                total_bytes=total_bytes,
            )
            if ok:
                success_count += 1
            else:
                logger.warning(f"User {tg_id}: failed inbound {ib.get('id')} ({ib.get('protocol')})")
            await asyncio.sleep(0.2)
        except Exception as e:
            logger.error(f"User {tg_id}: exception on inbound {ib.get('id')}: {e}")

    logger.info(f"User {tg_id}: {success_count}/{len(inbounds)} inbounds OK")
    return success_count > 0


async def get_expiry_for_user(tg_id: int) -> int | None:
    """Get expiry timestamp (ms) from x-ui for a user."""
    inbounds = await get_inbounds()
    for ib in inbounds:
        iid = ib.get("id", 0)
        # Try new per-inbound email, then old global email format
        client = _find_client_in_settings(ib, _make_email(tg_id, iid), str(tg_id))
        if client and client.get("expiryTime"):
            return client.get("expiryTime")
    # Fall back to fetching first inbound fully
    if inbounds:
        iid = inbounds[0].get("id", 0)
        full = await _get_inbound_full(iid)
        if full:
            client = _find_client_in_settings(full, _make_email(tg_id, iid), str(tg_id))
            if client:
                return client.get("expiryTime")
    return None


async def get_all_clients_traffic(tg_id: int) -> list[dict]:
    """Get traffic stats for a user across all inbounds."""
    inbounds = await get_inbounds()
    traffics = []
    for ib in inbounds:
        iid = ib.get("id", 0)
        email_new = _make_email(tg_id, iid)
        email_old = str(tg_id)
        for stat in (ib.get("clientStats") or []):
            if stat.get("email") in (email_new, email_old):
                traffics.append({
                    "up": stat.get("up", 0),
                    "down": stat.get("down", 0),
                    "inbound_id": iid,
                    "remark": ib.get("remark", ""),
                })
    return traffics


def fmt_bytes(b: int | float) -> str:
    b = float(b)
    if b == 0:
        return "0 Б"
    for unit in ["Б", "КБ", "МБ", "ГБ", "ТБ"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} ТБ"


async def user_exists_in_xui(tg_id: int) -> bool:
    """Check if user already has any clients in x-ui (persistent trial guard)."""
    inbounds = await get_inbounds()
    for ib in inbounds:
        iid = ib.get("id", 0)
        client = _find_client_in_settings(ib, _make_email(tg_id, iid), str(tg_id))
        if client:
            return True
    return False


async def toggle_client_in_all_inbounds(tg_id: int, sub_id: str, enable: bool) -> bool:
    """Enable or disable all clients for a user across all inbounds."""
    inbounds = await get_inbounds()
    if not inbounds:
        return False

    success_count = 0
    for ib in inbounds:
        iid = ib.get("id", 0)
        protocol = ib.get("protocol", "vless")
        email = _make_email(tg_id, iid)
        old_email = str(tg_id)

        existing = _find_client_in_settings(ib, email, old_email)
        if not existing:
            full = await _get_inbound_full(iid)
            if full:
                existing = _find_client_in_settings(full, email, old_email)

        if existing:
            existing["enable"] = enable
            existing["email"] = email
            existing["subId"] = sub_id
            if not _uses_xtls(ib):
                existing.pop("flow", None)
            ok = await _do_update_client(iid, existing, protocol)
            if ok:
                success_count += 1
            await asyncio.sleep(0.1)

    logger.info(f"toggle_client enable={enable} for user {tg_id}: {success_count}/{len(inbounds)} OK")
    return success_count > 0
