import aiosqlite
from datetime import datetime, timedelta
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                registered_at TEXT DEFAULT (datetime('now')),
                trial_used INTEGER DEFAULT 0,
                trial_used_at TEXT,
                subscription_end TEXT,
                sub_id TEXT UNIQUE,
                is_banned INTEGER DEFAULT 0,
                last_reminder TEXT,
                referred_by INTEGER DEFAULT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                plan TEXT NOT NULL,
                stars INTEGER NOT NULL,
                paid_at TEXT DEFAULT (datetime('now')),
                charge_id TEXT,
                is_gift INTEGER DEFAULT 0,
                gifted_by INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL UNIQUE,
                registered_at TEXT DEFAULT (datetime('now')),
                rewarded INTEGER DEFAULT 0
            )
        """)
        # Migrate existing columns
        for col, definition in [
            ("trial_used_at", "TEXT"),
            ("last_reminder", "TEXT"),
            ("is_banned", "INTEGER DEFAULT 0"),
            ("referred_by", "INTEGER DEFAULT NULL"),
        ]:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            except Exception:
                pass
        await db.commit()


async def get_user(tg_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def create_user(tg_id: int, username: str | None, first_name: str,
                       referred_by: int | None = None) -> dict:
    sub_id = f"vpn{tg_id}"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (tg_id, username, first_name, sub_id, referred_by) VALUES (?, ?, ?, ?, ?)",
            (tg_id, username, first_name, sub_id, referred_by),
        )
        await db.commit()
    return await get_user(tg_id)


async def update_subscription(tg_id: int, days: int):
    user = await get_user(tg_id)
    now = datetime.utcnow()
    if user and user.get("subscription_end"):
        try:
            current_end = datetime.fromisoformat(user["subscription_end"])
            base = current_end if current_end > now else now
        except Exception:
            base = now
    else:
        base = now
    new_end = base + timedelta(days=days)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET subscription_end = ?, last_reminder = NULL WHERE tg_id = ?",
            (new_end.isoformat(), tg_id),
        )
        await db.commit()


async def mark_trial_used(tg_id: int) -> bool:
    """Atomically mark trial as used. Returns True if the trial was reserved (wasn't used before)."""
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        # This UPDATE will only affect a row if trial_used == 0, making it atomic.
        cur = await db.execute(
            "UPDATE users SET trial_used = 1, trial_used_at = ? WHERE tg_id = ? AND trial_used = 0",
            (now, tg_id),
        )
        await db.commit()
        # Check how many rows were changed by the last statement using SQLite changes()
        async with db.execute("SELECT changes()") as c:
            row = await c.fetchone()
            changed = row[0] if row else 0
        return changed > 0


async def unmark_trial_used(tg_id: int):
    """Revert trial reservation if external provisioning failed."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET trial_used = 0, trial_used_at = NULL WHERE tg_id = ?",
            (tg_id,),
        )
        await db.commit()


async def add_payment(tg_id: int, plan: str, stars: int, charge_id: str = "",
                       is_gift: int = 0, gifted_by: int | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO payments (tg_id, plan, stars, charge_id, is_gift, gifted_by) VALUES (?, ?, ?, ?, ?, ?)",
            (tg_id, plan, stars, charge_id, is_gift, gifted_by),
        )
        await db.commit()


async def count_user_payments(tg_id: int) -> int:
    """Count non-gift payments for a user (to detect first purchase)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM payments WHERE tg_id = ? AND is_gift = 0", (tg_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_payment_history(tg_id: int, limit: int = 5) -> list[dict]:
    """Get last N payments for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM payments WHERE tg_id = ? ORDER BY paid_at DESC LIMIT ?",
            (tg_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_public_stats() -> dict:
    """Stats visible to all users."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_end > datetime('now')"
        ) as cur:
            active = (await cur.fetchone())[0]
        async with db.execute("SELECT SUM(stars) FROM payments WHERE is_gift = 0") as cur:
            total_stars = (await cur.fetchone())[0] or 0
    return {"total": total, "active": active, "total_stars": total_stars}


async def get_all_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users ORDER BY registered_at DESC") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE trial_used = 1") as cur:
            trials = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_end > datetime('now')"
        ) as cur:
            active = (await cur.fetchone())[0]
        async with db.execute("SELECT SUM(stars) FROM payments WHERE is_gift = 0") as cur:
            total_stars = (await cur.fetchone())[0] or 0
        async with db.execute("SELECT COUNT(*) FROM referrals") as cur:
            total_refs = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM referrals WHERE rewarded = 1") as cur:
            rewarded_refs = (await cur.fetchone())[0]
        return {
            "total": total,
            "trials": trials,
            "active": active,
            "total_stars": total_stars,
            "total_refs": total_refs,
            "rewarded_refs": rewarded_refs,
        }


async def get_users_expiring_soon() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM users
            WHERE subscription_end IS NOT NULL
              AND subscription_end > datetime('now')
              AND subscription_end <= datetime('now', '+4 days')
              AND (last_reminder IS NULL OR last_reminder != subscription_end)
        """) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def mark_reminder_sent(tg_id: int, subscription_end: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_reminder = ? WHERE tg_id = ?",
            (subscription_end, tg_id),
        )
        await db.commit()


async def has_active_subscription(tg_id: int) -> bool:
    user = await get_user(tg_id)
    if not user or not user.get("subscription_end"):
        return False
    try:
        end = datetime.fromisoformat(user["subscription_end"])
        return end > datetime.utcnow()
    except Exception:
        return False


# ── Referral functions ───────────────────────────────────────────────────────

async def add_referral(referrer_id: int, referred_id: int) -> bool:
    """Register a referral. Returns True if newly registered."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (?, ?)",
                (referrer_id, referred_id),
            )
            await db.commit()
            async with db.execute(
                "SELECT id FROM referrals WHERE referrer_id = ? AND referred_id = ?",
                (referrer_id, referred_id),
            ) as cur:
                return await cur.fetchone() is not None
        except Exception:
            return False


async def get_referral_stats(referrer_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (referrer_id,)
        ) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND rewarded = 1", (referrer_id,)
        ) as cur:
            rewarded = (await cur.fetchone())[0]
    return {"total": total, "rewarded": rewarded}


async def get_unrewarded_referral(referred_id: int) -> dict | None:
    """Get unrewarded referral record for a newly paying user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM referrals WHERE referred_id = ? AND rewarded = 0", (referred_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def mark_referral_rewarded(referral_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE referrals SET rewarded = 1 WHERE id = ?", (referral_id,))
        await db.commit()
