import json
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import (
    clear_session_cookie,
    generate_oauth_state,
    get_user_id_from_request,
    hash_password,
    set_session_cookie,
    verify_oauth_state,
    verify_password,
)
from app.config import get_settings
from app.database import get_db, init_db
from app.models import ConnectedDevice, DailySnapshot, Reward, TierAssignment, User, WellnessScore
from app.providers.fitbit import exchange_fitbit_code, fitbit_configured, get_fitbit_auth_url
from app.providers.garmin import (
    exchange_garmin_verifier,
    garmin_configured,
    get_garmin_authorize_url,
    get_garmin_request_token,
)
from app.sync import seed_demo_data, sync_user_devices
from app.tiers import TIERS
from app.wellness_score import days_ago

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

app = FastAPI(title="FitCover India", version="0.1.0")


@app.on_event("startup")
def on_startup():
    init_db()


def _redirect_login():
    return RedirectResponse("/login", status_code=303)


def _get_tier_info(db: Session, user_id: str) -> dict:
    tier_row = (
        db.query(TierAssignment)
        .filter_by(user_id=user_id)
        .order_by(TierAssignment.created_at.desc())
        .first()
    )
    tier_name = tier_row.tier if tier_row else "bronze"
    tier_def = next(t for t in TIERS if t.name == tier_name)
    return {
        "name": tier_name,
        "label": tier_def.label,
        "color": tier_def.color,
        "benefits": tier_def.benefits,
        "score": tier_row.score if tier_row else 0,
        "active_days": tier_row.active_days if tier_row else 0,
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if get_user_id_from_request(request):
        return RedirectResponse("/dashboard")
    return TEMPLATES.TemplateResponse(request, "index.html", {})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
async def login_action(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    email = str(form.get("email", ""))
    password = str(form.get("password", ""))
    user = db.query(User).filter_by(email=email).first()
    if not user or not verify_password(password, user.password_hash):
        return TEMPLATES.TemplateResponse(
            request, "login.html", {"error": "Invalid credentials"}, status_code=401
        )
    response = RedirectResponse("/dashboard", status_code=303)
    set_session_cookie(response, user.id)
    return response


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "register.html", {"error": None})


@app.post("/register")
async def register_action(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    email = str(form.get("email", ""))
    password = str(form.get("password", ""))
    name = str(form.get("name", "")) or None

    if len(password) < 8:
        return TEMPLATES.TemplateResponse(
            request, "register.html", {"error": "Password must be at least 8 characters"}, status_code=400
        )
    if db.query(User).filter_by(email=email).first():
        return TEMPLATES.TemplateResponse(
            request, "register.html", {"error": "Email already registered"}, status_code=409
        )

    user = User(email=email, name=name, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)

    response = RedirectResponse("/dashboard", status_code=303)
    set_session_cookie(response, user.id)
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    clear_session_cookie(response)
    return response


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return _redirect_login()

    user = db.get(User, user_id)
    window_start = days_ago(30)
    scores = (
        db.query(WellnessScore)
        .filter(WellnessScore.user_id == user_id, WellnessScore.date >= window_start)
        .order_by(WellnessScore.date.asc())
        .all()
    )
    latest_score = scores[-1] if scores else None
    latest_snapshot = (
        db.query(DailySnapshot)
        .filter_by(user_id=user_id, source="merged")
        .order_by(DailySnapshot.date.desc())
        .first()
    )
    has_devices = db.query(ConnectedDevice).filter_by(user_id=user_id).count() > 0

    return TEMPLATES.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "active": "dashboard",
            "latest_score": latest_score,
            "latest_snapshot": latest_snapshot,
            "scores": scores,
            "tier": _get_tier_info(db, user_id),
            "has_devices": has_devices,
        },
    )


@app.get("/dashboard/devices", response_class=HTMLResponse)
def devices_page(request: Request, db: Session = Depends(get_db)):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return _redirect_login()

    user = db.get(User, user_id)
    connected_devices = db.query(ConnectedDevice).filter_by(user_id=user_id).all()
    connected_map = {d.provider: d for d in connected_devices}

    providers = [
        {"id": "fitbit", "name": "Fitbit", "configured": fitbit_configured(), "connected": "fitbit" in connected_map},
        {"id": "garmin", "name": "Garmin Connect", "configured": garmin_configured(), "connected": "garmin" in connected_map},
    ]

    return TEMPLATES.TemplateResponse(
        request,
        "devices.html",
        {
            "user": user,
            "active": "devices",
            "providers": providers,
            "connected": request.query_params.get("connected"),
            "error": request.query_params.get("error"),
        },
    )


@app.get("/dashboard/rewards", response_class=HTMLResponse)
def rewards_page(request: Request, db: Session = Depends(get_db)):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return _redirect_login()

    user = db.get(User, user_id)
    rewards = db.query(Reward).filter_by(user_id=user_id).order_by(Reward.created_at.desc()).all()
    current_tier = _get_tier_info(db, user_id)

    return TEMPLATES.TemplateResponse(
        request,
        "rewards.html",
        {
            "user": user,
            "active": "rewards",
            "rewards": rewards,
            "all_tiers": TIERS,
            "current_tier": current_tier,
        },
    )


@app.post("/rewards/{reward_id}/claim")
def claim_reward(reward_id: str, request: Request, db: Session = Depends(get_db)):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return _redirect_login()

    reward = db.query(Reward).filter_by(id=reward_id, user_id=user_id, status="available").first()
    if reward:
        reward.status = "claimed"
        db.commit()
    return RedirectResponse("/dashboard/rewards", status_code=303)


@app.post("/sync")
async def sync_action(request: Request, db: Session = Depends(get_db)):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return _redirect_login()
    await sync_user_devices(db, user_id)
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/sync/demo")
def sync_demo(request: Request, db: Session = Depends(get_db)):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return _redirect_login()
    seed_demo_data(db, user_id)
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/devices/fitbit/connect")
def fitbit_connect(request: Request):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return _redirect_login()
    if not fitbit_configured():
        return RedirectResponse("/dashboard/devices?error=fitbit_not_configured", status_code=303)
    state = generate_oauth_state(user_id)
    return RedirectResponse(get_fitbit_auth_url(state))


@app.get("/devices/fitbit/callback")
async def fitbit_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        return RedirectResponse(f"/dashboard/devices?error={error}", status_code=303)
    if not code or not state:
        return RedirectResponse("/dashboard/devices?error=missing_code", status_code=303)

    user_id = verify_oauth_state(state)
    if not user_id:
        return RedirectResponse("/dashboard/devices?error=invalid_state", status_code=303)

    tokens = await exchange_fitbit_code(code)
    device = db.query(ConnectedDevice).filter_by(user_id=user_id, provider="fitbit").first()
    expiry = datetime.utcnow().timestamp() + tokens["expires_in"]
    if device:
        device.access_token = tokens["access_token"]
        device.refresh_token = tokens["refresh_token"]
        device.token_expiry = datetime.utcfromtimestamp(expiry)
        device.external_user_id = tokens["user_id"]
    else:
        db.add(
            ConnectedDevice(
                user_id=user_id,
                provider="fitbit",
                access_token=tokens["access_token"],
                refresh_token=tokens["refresh_token"],
                token_expiry=datetime.utcfromtimestamp(expiry),
                external_user_id=tokens["user_id"],
            )
        )
    db.commit()
    await sync_user_devices(db, user_id, days=7)
    return RedirectResponse("/dashboard/devices?connected=fitbit", status_code=303)


@app.get("/devices/garmin/connect")
def garmin_connect(request: Request):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return _redirect_login()
    if not garmin_configured():
        return RedirectResponse("/dashboard/devices?error=garmin_not_configured", status_code=303)

    tokens = get_garmin_request_token()
    state = generate_oauth_state(user_id)
    redirect = RedirectResponse(get_garmin_authorize_url(tokens["oauth_token"]))
    redirect.set_cookie(
        "garmin_oauth",
        json.dumps(
            {
                "request_token": tokens["oauth_token"],
                "request_token_secret": tokens["oauth_token_secret"],
                "state": state,
            }
        ),
        httponly=True,
        max_age=600,
        samesite="lax",
    )
    return redirect


@app.get("/devices/garmin/callback")
async def garmin_callback(
    request: Request,
    db: Session = Depends(get_db),
    oauth_token: str | None = None,
    oauth_verifier: str | None = None,
):
    if not oauth_token or not oauth_verifier:
        return RedirectResponse("/dashboard/devices?error=missing_garmin_verifier", status_code=303)

    raw = request.cookies.get("garmin_oauth")
    if not raw:
        return RedirectResponse("/dashboard/devices?error=garmin_session_expired", status_code=303)

    stored = json.loads(raw)
    user_id = verify_oauth_state(stored["state"])
    if not user_id:
        return RedirectResponse("/dashboard/devices?error=invalid_state", status_code=303)

    tokens = exchange_garmin_verifier(
        stored["request_token"],
        stored["request_token_secret"],
        oauth_verifier,
    )

    device = db.query(ConnectedDevice).filter_by(user_id=user_id, provider="garmin").first()
    if device:
        device.access_token = tokens["oauth_token"]
        device.token_secret = tokens["oauth_token_secret"]
    else:
        db.add(
            ConnectedDevice(
                user_id=user_id,
                provider="garmin",
                access_token=tokens["oauth_token"],
                token_secret=tokens["oauth_token_secret"],
            )
        )
    db.commit()
    await sync_user_devices(db, user_id, days=7)

    response = RedirectResponse("/dashboard/devices?connected=garmin", status_code=303)
    response.delete_cookie("garmin_oauth")
    return response


@app.get("/api/insurer/users")
def insurer_export(
    request: Request,
    db: Session = Depends(get_db),
    user_id: str | None = None,
    email: str | None = None,
    x_insurer_api_key: str | None = Header(default=None),
):
    settings = get_settings()
    if x_insurer_api_key != settings.insurer_api_key or not x_insurer_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if not user_id and not email:
        raise HTTPException(status_code=400, detail="Provide userId or email")

    if user_id:
        user = db.query(User).filter_by(id=user_id).first()
    else:
        user = db.query(User).filter_by(email=email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    window_start = days_ago(30)
    scores = (
        db.query(WellnessScore)
        .filter(WellnessScore.user_id == user.id, WellnessScore.date >= window_start)
        .order_by(WellnessScore.date.desc())
        .all()
    )
    snapshots = (
        db.query(DailySnapshot)
        .filter(
            DailySnapshot.user_id == user.id,
            DailySnapshot.source == "merged",
            DailySnapshot.date >= window_start,
        )
        .order_by(DailySnapshot.date.desc())
        .all()
    )
    devices = db.query(ConnectedDevice).filter_by(user_id=user.id).all()
    tier = _get_tier_info(db, user.id)
    avg_score = round(sum(s.score for s in scores) / len(scores)) if scores else 0

    return {
        "user_id": user.id,
        "email": user.email,
        "name": user.name,
        "wellness": {
            "tier": tier["name"],
            "tier_label": tier["label"],
            "average_score_30d": avg_score,
            "active_days_30d": tier["active_days"],
            "latest_score": scores[0].score if scores else None,
            "score_trend": [{"date": s.date.strftime("%Y-%m-%d"), "score": s.score} for s in scores],
        },
        "devices": [{"provider": d.provider, "last_sync_at": d.last_sync_at} for d in devices],
        "daily_metrics": [
            {
                "date": s.date.strftime("%Y-%m-%d"),
                "steps": s.steps,
                "active_minutes": s.active_minutes,
                "sleep_hours": s.sleep_hours,
                "resting_hr": s.resting_hr,
            }
            for s in snapshots
        ],
        "disclaimer": "Rewards-only wellness data. No premium increases based on health decline.",
    }
