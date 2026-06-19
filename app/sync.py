import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import ConnectedDevice, DailySnapshot, Reward, TierAssignment, WellnessScore
from app.providers.fitbit import fetch_fitbit_daily_data, refresh_fitbit_token
from app.providers.garmin import fetch_garmin_daily_data
from app.tiers import resolve_tier, rewards_for_tier
from app.wellness_score import (
    DailyMetrics,
    average_score,
    calculate_daily_score,
    count_active_days,
    days_ago,
    start_of_day,
)


def _format_date(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _merge_snapshots(data: list[dict]) -> dict:
    merged = {
        "date": data[0]["date"],
        "steps": 0,
        "active_minutes": 0,
        "resting_hr": None,
        "sleep_hours": None,
        "workout_count": 0,
    }
    for item in data:
        merged["steps"] = max(merged["steps"], item["steps"])
        merged["active_minutes"] = max(merged["active_minutes"], item["active_minutes"])
        merged["resting_hr"] = item.get("resting_hr") or merged["resting_hr"]
        merged["sleep_hours"] = item.get("sleep_hours") or merged["sleep_hours"]
        merged["workout_count"] += item.get("workout_count", 0)
    return merged


def _upsert_snapshot(db: Session, user_id: str, date: datetime, source: str, data: dict) -> None:
    row = (
        db.query(DailySnapshot)
        .filter_by(user_id=user_id, date=date, source=source)
        .first()
    )
    if row:
        row.steps = data["steps"]
        row.active_minutes = data["active_minutes"]
        row.resting_hr = data.get("resting_hr")
        row.sleep_hours = data.get("sleep_hours")
        row.workout_count = data.get("workout_count", 0)
    else:
        db.add(
            DailySnapshot(
                user_id=user_id,
                date=date,
                source=source,
                steps=data["steps"],
                active_minutes=data["active_minutes"],
                resting_hr=data.get("resting_hr"),
                sleep_hours=data.get("sleep_hours"),
                workout_count=data.get("workout_count", 0),
            )
        )


async def sync_user_devices(db: Session, user_id: str, days: int = 30) -> dict:
    devices = db.query(ConnectedDevice).filter_by(user_id=user_id).all()

    for device in devices:
        access_token = device.access_token
        token_secret = device.token_secret

        if device.provider == "fitbit" and device.refresh_token and device.token_expiry:
            if device.token_expiry < datetime.utcnow():
                refreshed = await refresh_fitbit_token(device.refresh_token)
                access_token = refreshed["access_token"]
                device.access_token = refreshed["access_token"]
                device.refresh_token = refreshed["refresh_token"]
                device.token_expiry = datetime.utcnow() + timedelta(seconds=refreshed["expires_in"])

        for i in range(days):
            date_str = _format_date(days_ago(i))
            date = start_of_day(datetime.strptime(date_str, "%Y-%m-%d"))
            try:
                if device.provider == "fitbit":
                    daily = await fetch_fitbit_daily_data(
                        access_token, device.external_user_id or "", date_str
                    )
                elif device.provider == "garmin":
                    daily = await fetch_garmin_daily_data(access_token, token_secret or "", date_str)
                else:
                    continue
                _upsert_snapshot(db, user_id, date, device.provider, daily)
            except Exception as exc:
                print(f"Sync failed for {device.provider} on {date_str}: {exc}")

        device.last_sync_at = datetime.utcnow()

    db.commit()
    _rebuild_merged_snapshots(db, user_id, days)
    recalculate_scores_and_tier(db, user_id)
    return {"synced_days": days, "provider_count": len(devices)}


def _rebuild_merged_snapshots(db: Session, user_id: str, days: int) -> None:
    for i in range(days):
        date = start_of_day(days_ago(i))
        snapshots = (
            db.query(DailySnapshot)
            .filter(
                DailySnapshot.user_id == user_id,
                DailySnapshot.date == date,
                DailySnapshot.source.in_(["garmin", "fitbit"]),
            )
            .all()
        )
        if not snapshots:
            continue
        merged = _merge_snapshots(
            [
                {
                    "date": _format_date(s.date),
                    "steps": s.steps,
                    "active_minutes": s.active_minutes,
                    "resting_hr": s.resting_hr,
                    "sleep_hours": s.sleep_hours,
                    "workout_count": s.workout_count,
                }
                for s in snapshots
            ]
        )
        _upsert_snapshot(db, user_id, date, "merged", merged)
    db.commit()


def recalculate_scores_and_tier(db: Session, user_id: str) -> None:
    window_start = days_ago(30)
    snapshots = (
        db.query(DailySnapshot)
        .filter(
            DailySnapshot.user_id == user_id,
            DailySnapshot.source == "merged",
            DailySnapshot.date >= window_start,
        )
        .order_by(DailySnapshot.date.asc())
        .all()
    )

    metrics = [
        DailyMetrics(s.steps, s.active_minutes, s.resting_hr, s.sleep_hours, s.workout_count)
        for s in snapshots
    ]
    active_days = count_active_days(metrics)

    for snapshot in snapshots:
        breakdown = calculate_daily_score(
            DailyMetrics(
                snapshot.steps,
                snapshot.active_minutes,
                snapshot.resting_hr,
                snapshot.sleep_hours,
                snapshot.workout_count,
            ),
            active_days,
        )
        row = (
            db.query(WellnessScore)
            .filter_by(user_id=user_id, date=snapshot.date)
            .first()
        )
        if row:
            row.score = breakdown.score
            row.activity = breakdown.activity
            row.cardio = breakdown.cardio
            row.recovery = breakdown.recovery
            row.consistency = breakdown.consistency
        else:
            db.add(
                WellnessScore(
                    user_id=user_id,
                    date=snapshot.date,
                    score=breakdown.score,
                    activity=breakdown.activity,
                    cardio=breakdown.cardio,
                    recovery=breakdown.recovery,
                    consistency=breakdown.consistency,
                )
            )

    db.commit()

    scores = (
        db.query(WellnessScore.score)
        .filter(WellnessScore.user_id == user_id, WellnessScore.date >= window_start)
        .all()
    )
    avg_score = average_score([s[0] for s in scores])

    latest_tier = (
        db.query(TierAssignment)
        .filter_by(user_id=user_id)
        .order_by(TierAssignment.created_at.desc())
        .first()
    )
    current_tier = latest_tier.tier if latest_tier else "bronze"
    new_tier = resolve_tier(avg_score, active_days, current_tier)

    if not latest_tier or new_tier.name != current_tier:
        db.add(
            TierAssignment(
                user_id=user_id,
                tier=new_tier.name,
                score=avg_score,
                active_days=active_days,
            )
        )
        db.commit()
        _grant_tier_rewards(db, user_id, new_tier.name)


def _grant_tier_rewards(db: Session, user_id: str, tier: str) -> None:
    existing = db.query(Reward).filter_by(user_id=user_id, tier_required=tier).count()
    if existing:
        return
    for reward in rewards_for_tier(tier):
        if reward["type"] in ("cashback", "coupon") or "cashback" in reward["title"] or "coupon" in reward["title"]:
            db.add(
                Reward(
                    user_id=user_id,
                    type=reward["type"],
                    title=reward["title"],
                    value=reward["value"],
                    tier_required=tier,
                    status="available",
                    expires_at=datetime.utcnow() + timedelta(days=90),
                )
            )
    db.commit()


def seed_demo_data(db: Session, user_id: str) -> None:
    for i in range(30):
        date = start_of_day(days_ago(i))
        steps = random.randint(4000, 12000)
        active_minutes = random.randint(15, 60)
        sleep_hours = round(random.uniform(5.5, 8.5), 1)
        resting_hr = random.randint(58, 78)
        _upsert_snapshot(
            db,
            user_id,
            date,
            "merged",
            {
                "steps": steps,
                "active_minutes": active_minutes,
                "resting_hr": resting_hr,
                "sleep_hours": sleep_hours,
                "workout_count": 1 if steps > 7000 else 0,
            },
        )
    db.commit()
    recalculate_scores_and_tier(db, user_id)
