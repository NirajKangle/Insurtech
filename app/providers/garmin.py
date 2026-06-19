from datetime import datetime
from typing import Any

import httpx
from requests_oauthlib import OAuth1Session

from app.config import get_settings
from app.providers.fitbit import app_url


def garmin_configured() -> bool:
    return get_settings().garmin_configured


def get_garmin_oauth_session(token: str | None = None, token_secret: str | None = None) -> OAuth1Session:
    settings = get_settings()
    return OAuth1Session(
        settings.garmin_consumer_key,
        client_secret=settings.garmin_consumer_secret,
        resource_owner_key=token,
        resource_owner_secret=token_secret,
        callback_uri=app_url("/devices/garmin/callback"),
    )


def get_garmin_request_token() -> dict[str, str]:
    oauth = get_garmin_oauth_session()
    tokens = oauth.fetch_request_token(
        "https://connectapi.garmin.com/oauth-service/oauth/request_token"
    )
    return {"oauth_token": tokens["oauth_token"], "oauth_token_secret": tokens["oauth_token_secret"]}


def get_garmin_authorize_url(request_token: str) -> str:
    return f"https://connect.garmin.com/oauthConfirm?oauth_token={request_token}"


def exchange_garmin_verifier(
    request_token: str,
    request_token_secret: str,
    verifier: str,
) -> dict[str, str]:
    oauth = OAuth1Session(
        get_settings().garmin_consumer_key,
        client_secret=get_settings().garmin_consumer_secret,
        resource_owner_key=request_token,
        resource_owner_secret=request_token_secret,
        verifier=verifier,
    )
    return oauth.fetch_access_token(
        "https://connectapi.garmin.com/oauth-service/oauth/access_token"
    )


async def fetch_garmin_daily_data(access_token: str, token_secret: str, date: str) -> dict:
    start = int(datetime.strptime(date, "%Y-%m-%d").replace(hour=0, minute=0, second=0).timestamp())
    end = start + 86400 - 1

    oauth = OAuth1Session(
        get_settings().garmin_consumer_key,
        client_secret=get_settings().garmin_consumer_secret,
        resource_owner_key=access_token,
        resource_owner_secret=token_secret,
    )

    steps = active_minutes = 0
    resting_hr = sleep_hours = None

    async with httpx.AsyncClient() as client:
        for path, handler in [
            (f"/dailies?uploadStartTimeInSeconds={start}&uploadEndTimeInSeconds={end}", "daily"),
            (f"/sleeps?uploadStartTimeInSeconds={start}&uploadEndTimeInSeconds={end}", "sleep"),
        ]:
            url = f"https://apis.garmin.com/wellness-api/rest{path}"
            signed = oauth.sign(url, "GET")
            try:
                res = await client.get(url, headers={"Authorization": signed["Authorization"]})
                res.raise_for_status()
                data: list[dict[str, Any]] = res.json()
                if handler == "daily" and data:
                    day = data[0]
                    steps = day.get("steps", 0)
                    active_minutes = round(day.get("activeTimeInSeconds", 0) / 60)
                    resting_hr = day.get("restingHeartRateInBeatsPerMinute")
                if handler == "sleep" and data:
                    sleep = data[0]
                    if sleep.get("durationInSeconds"):
                        sleep_hours = round(sleep["durationInSeconds"] / 3600, 1)
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
