import base64
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings


def fitbit_configured() -> bool:
    return get_settings().fitbit_configured


def garmin_configured() -> bool:
    return get_settings().garmin_configured


def app_url(path: str = "") -> str:
    return f"{get_settings().app_url}{path}"


def get_fitbit_auth_url(state: str) -> str:
    settings = get_settings()
    params = {
        "client_id": settings.fitbit_client_id,
        "response_type": "code",
        "scope": "activity heartrate sleep profile",
        "redirect_uri": app_url("/devices/fitbit/callback"),
        "state": state,
    }
    return f"https://www.fitbit.com/oauth2/authorize?{urlencode(params)}"


async def exchange_fitbit_code(code: str) -> dict[str, Any]:
    settings = get_settings()
    credentials = base64.b64encode(
        f"{settings.fitbit_client_id}:{settings.fitbit_client_secret}".encode()
    ).decode()

    async with httpx.AsyncClient() as client:
        res = await client.post(
            "https://api.fitbit.com/oauth2/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "client_id": settings.fitbit_client_id,
                "grant_type": "authorization_code",
                "redirect_uri": app_url("/devices/fitbit/callback"),
                "code": code,
            },
        )
        res.raise_for_status()
        return res.json()


async def refresh_fitbit_token(refresh_token: str) -> dict[str, Any]:
    settings = get_settings()
    credentials = base64.b64encode(
        f"{settings.fitbit_client_id}:{settings.fitbit_client_secret}".encode()
    ).decode()

    async with httpx.AsyncClient() as client:
        res = await client.post(
            "https://api.fitbit.com/oauth2/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        res.raise_for_status()
        return res.json()


async def _fitbit_get(access_token: str, path: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"https://api.fitbit.com/1/user/{path}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        res.raise_for_status()
        return res.json()


async def fetch_fitbit_daily_data(access_token: str, fitbit_user_id: str, date: str) -> dict:
    steps = active_minutes = 0
    resting_hr = sleep_hours = None

    try:
        activity = await _fitbit_get(access_token, f"-{fitbit_user_id}/activities/date/{date}.json")
        summary = activity.get("summary", {})
        steps = summary.get("steps", 0)
        active_minutes = summary.get("fairlyActiveMinutes", 0) + summary.get("veryActiveMinutes", 0)
    except httpx.HTTPError:
        pass

    try:
        heart = await _fitbit_get(access_token, f"-{fitbit_user_id}/activities/heart/date/{date}/1d.json")
        resting_hr = heart.get("activities-heart", [{}])[0].get("value", {}).get("restingHeartRate")
    except httpx.HTTPError:
        pass

    try:
        sleep = await _fitbit_get(access_token, f"-{fitbit_user_id}/sleep/date/{date}.json")
        minutes = sleep.get("summary", {}).get("totalMinutesAsleep")
        if minutes:
            sleep_hours = round(minutes / 60, 1)
    except httpx.HTTPError:
        pass

    return {
        "date": date,
        "steps": steps,
        "active_minutes": active_minutes,
        "resting_hr": resting_hr,
        "sleep_hours": sleep_hours,
        "workout_count": 0,
    }
