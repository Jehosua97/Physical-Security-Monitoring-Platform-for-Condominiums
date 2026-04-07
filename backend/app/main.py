import asyncio
import contextlib
import os
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine, get_db, utcnow
from .media import media_store
from .models import Alert, Camera, Device, RemoteAction, Site, VisitorEvent
from .realtime import live_hub
from .thingsboard import thingsboard_bridge


BASE_DIR = Path(__file__).resolve().parent
SITE_OFFLINE_SECONDS = int(os.getenv("SITE_OFFLINE_SECONDS", "40"))
CAMERA_OFFLINE_SECONDS = int(os.getenv("CAMERA_OFFLINE_SECONDS", "30"))
MONITORING_INTERVAL_SECONDS = int(os.getenv("MONITORING_INTERVAL_SECONDS", "8"))
THINGSBOARD_SYNC_INTERVAL_SECONDS = int(os.getenv("THINGSBOARD_SYNC_INTERVAL_SECONDS", "20"))

app = FastAPI(
    title="Plataforma de Monitoreo de Seguridad Fisica",
    version="0.1.0",
    description="Prototipo Stage 1 en Docker para monitoreo operativo de condominios.",
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class SiteRegister(BaseModel):
    id: str
    name: str
    address: str = ""


class SiteHeartbeat(BaseModel):
    site_id: str
    site_name: str | None = None
    address: str | None = None
    status: str = "online"
    edge_id: str | None = None


class DeviceHeartbeat(BaseModel):
    site_id: str
    device_id: str
    device_type: str
    name: str
    status: str = "online"


class CameraStatusUpdate(BaseModel):
    site_id: str
    camera_id: str
    name: str
    status: str = "online"
    stream_url: str | None = None
    generate_snapshot: bool = True
    snapshot_label: str | None = None


class VisitorCheckin(BaseModel):
    site_id: str
    visitor_name: str
    unit_to_visit: str
    host_name: str
    id_type: str
    status: str = "approved"
    notes: str | None = None


class AlertCreate(BaseModel):
    site_id: str
    source_type: str
    source_id: str
    severity: str
    message: str
    status: str = "open"
    code: str = "custom_alert"


class VisitorDecision(BaseModel):
    decision: str
    operator_name: str = "Centro de monitoreo"
    trigger_remote_action: bool = False


class RemoteActionCreate(BaseModel):
    action_type: str
    target_id: str
    command: str
    requested_by: str = "Centro de monitoreo"
    payload: dict = Field(default_factory=dict)


class RemoteActionStatusUpdate(BaseModel):
    status: str
    result_message: str | None = None


def wait_for_dependencies() -> None:
    for attempt in range(1, 31):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            media_store.ensure_bucket()
            return
        except Exception as exc:
            if attempt == 30:
                raise RuntimeError("dependencies did not become available in time") from exc
            import time

            time.sleep(2)


def ensure_site(
    db: Session,
    *,
    site_id: str,
    site_name: str | None = None,
    address: str | None = None,
    status: str = "online",
) -> Site:
    site = db.get(Site, site_id)
    if site is None:
        site = Site(
            id=site_id,
            name=site_name or site_id.replace("-", " ").title(),
            address=address or "Condominio demo",
            status=status,
            last_seen=utcnow(),
        )
        db.add(site)
    else:
        if site_name:
            site.name = site_name
        if address:
            site.address = address
        site.status = status
        site.last_seen = utcnow()
    return site


def upsert_device(
    db: Session,
    *,
    site_id: str,
    device_id: str,
    device_type: str,
    name: str,
    status: str,
) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        device = Device(
            id=device_id,
            site_id=site_id,
            type=device_type,
            name=name,
            status=status,
            last_seen=utcnow(),
            details={},
        )
        db.add(device)
    else:
        device.site_id = site_id
        device.type = device_type
        device.name = name
        device.status = status
        device.last_seen = utcnow()
    return device


def ensure_alert(
    db: Session,
    *,
    code: str,
    site_id: str,
    source_type: str,
    source_id: str,
    severity: str,
    message: str,
    status: str = "open",
) -> Alert:
    alert = db.execute(
        select(Alert).where(
            Alert.code == code,
            Alert.site_id == site_id,
            Alert.source_id == source_id,
            Alert.status.in_(["open", "acknowledged"]),
        )
    ).scalar_one_or_none()
    if alert is not None:
        alert.message = message
        alert.severity = severity
        return alert

    alert = Alert(
        id=uuid.uuid4().hex,
        code=code,
        site_id=site_id,
        source_type=source_type,
        source_id=source_id,
        severity=severity,
        message=message,
        status=status,
    )
    db.add(alert)
    return alert


def close_alerts(db: Session, *, code: str, site_id: str, source_id: str) -> None:
    alerts = db.execute(
        select(Alert).where(
            Alert.code == code,
            Alert.site_id == site_id,
            Alert.source_id == source_id,
            Alert.status.in_(["open", "acknowledged"]),
        )
    ).scalars()
    now = utcnow()
    for alert in alerts:
        alert.status = "closed"
        alert.closed_at = now


def camera_summary(camera: Camera) -> dict:
    return {
        "camera_id": camera.id,
        "site_id": camera.site_id,
        "name": camera.name,
        "status": camera.status,
        "snapshot_url": camera.snapshot_url,
        "stream_url": camera.stream_url,
        "last_seen": camera.last_seen.isoformat(),
    }


def visitor_summary(event: VisitorEvent) -> dict:
    return {
        "event_id": event.id,
        "site_id": event.site_id,
        "visitor_name": event.visitor_name,
        "unit_to_visit": event.unit_to_visit,
        "host_name": event.host_name,
        "id_type": event.id_type,
        "snapshot_url": event.snapshot_url,
        "status": event.status,
        "notes": event.notes,
        "timestamp": event.created_at.isoformat(),
    }


def alert_summary(alert: Alert) -> dict:
    return {
        "alert_id": alert.id,
        "code": alert.code,
        "site_id": alert.site_id,
        "source_type": alert.source_type,
        "source_id": alert.source_id,
        "severity": alert.severity,
        "message": alert.message,
        "status": alert.status,
        "timestamp": alert.created_at.isoformat(),
    }


def action_summary(action: RemoteAction) -> dict:
    return {
        "action_id": action.id,
        "site_id": action.site_id,
        "action_type": action.action_type,
        "target_id": action.target_id,
        "command": action.command,
        "requested_by": action.requested_by,
        "payload": action.payload,
        "status": action.status,
        "result_message": action.result_message,
        "created_at": action.created_at.isoformat(),
        "started_at": action.started_at.isoformat() if action.started_at else None,
        "completed_at": action.completed_at.isoformat() if action.completed_at else None,
    }


def create_remote_action(
    db: Session,
    *,
    site_id: str,
    action_type: str,
    target_id: str,
    command: str,
    requested_by: str,
    payload: dict | None = None,
) -> RemoteAction:
    action = RemoteAction(
        id=uuid.uuid4().hex,
        site_id=site_id,
        action_type=action_type,
        target_id=target_id,
        command=command,
        requested_by=requested_by,
        payload=payload or {},
        status="pending",
    )
    db.add(action)
    return action


def build_dashboard_overview(db: Session) -> dict:
    now = utcnow()
    sites = db.execute(select(Site).order_by(Site.id)).scalars().all()
    cameras = db.execute(select(Camera).order_by(Camera.last_seen.desc())).scalars().all()
    latest_events = db.execute(
        select(VisitorEvent).order_by(VisitorEvent.created_at.desc()).limit(10)
    ).scalars().all()
    latest_alerts = db.execute(select(Alert).order_by(Alert.created_at.desc()).limit(10)).scalars().all()

    site_cards = []
    for site in sites:
        site_cameras = [camera for camera in cameras if camera.site_id == site.id]
        site_alerts = [alert for alert in latest_alerts if alert.site_id == site.id and alert.status != "closed"]
        site_events = [event for event in latest_events if event.site_id == site.id]
        site_cards.append(
            {
                "site_id": site.id,
                "name": site.name,
                "address": site.address,
                "status": site.status,
                "last_seen": site.last_seen.isoformat(),
                "active_cameras": sum(1 for camera in site_cameras if camera.status == "online"),
                "recent_alerts": len(site_alerts),
                "recent_visitors": len(site_events),
                "latest_snapshot_url": site_cameras[0].snapshot_url if site_cameras else None,
            }
        )

    return {
        "generated_at": now.isoformat(),
        "kpis": {
            "sites_online": sum(
                1 for site in sites if site.status == "online" and now - site.last_seen <= timedelta(seconds=SITE_OFFLINE_SECONDS)
            ),
            "sites_total": len(sites),
            "cameras_online": sum(
                1
                for camera in cameras
                if camera.status == "online" and now - camera.last_seen <= timedelta(seconds=CAMERA_OFFLINE_SECONDS)
            ),
            "visitors_total": db.scalar(select(func.count(VisitorEvent.id))) or 0,
            "alerts_open": db.scalar(select(func.count(Alert.id)).where(Alert.status.in_(["open", "acknowledged"]))) or 0,
        },
        "sites": site_cards,
        "latest_alerts": [alert_summary(alert) for alert in latest_alerts],
        "latest_visitors": [visitor_summary(event) for event in latest_events],
        "latest_cameras": [camera_summary(camera) for camera in cameras[:8]],
    }


def build_site_snapshot(db: Session, site_id: str) -> dict | None:
    site = db.get(Site, site_id)
    if site is None:
        return None

    camera_cutoff = utcnow() - timedelta(seconds=CAMERA_OFFLINE_SECONDS)
    active_cameras = db.scalar(
        select(func.count(Camera.id)).where(
            Camera.site_id == site_id,
            Camera.status == "online",
            Camera.last_seen >= camera_cutoff,
        )
    ) or 0
    open_alerts = db.scalar(
        select(func.count(Alert.id)).where(
            Alert.site_id == site_id,
            Alert.status.in_(["open", "acknowledged"]),
        )
    ) or 0
    latest_visitor = db.execute(
        select(VisitorEvent)
        .where(VisitorEvent.site_id == site_id)
        .order_by(VisitorEvent.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    latest_alert = db.execute(
        select(Alert).where(Alert.site_id == site_id).order_by(Alert.created_at.desc()).limit(1)
    ).scalar_one_or_none()

    return {
        "site_id": site.id,
        "site_name": site.name,
        "address": site.address,
        "status": site.status,
        "active_cameras": active_cameras,
        "open_alerts": open_alerts,
        "last_seen": site.last_seen.isoformat(),
        "last_seen_epoch": int(site.last_seen.timestamp() * 1000),
        "latest_visitor_name": latest_visitor.visitor_name if latest_visitor else "",
        "latest_visitor_status": latest_visitor.status if latest_visitor else "",
        "latest_visitor_unit": latest_visitor.unit_to_visit if latest_visitor else "",
        "latest_alert_message": latest_alert.message if latest_alert else "",
        "latest_alert_severity": latest_alert.severity if latest_alert else "",
    }


def build_camera_snapshot(db: Session, camera_id: str) -> dict | None:
    camera = db.get(Camera, camera_id)
    if camera is None:
        return None

    site = db.get(Site, camera.site_id)
    return {
        "camera_id": camera.id,
        "camera_name": camera.name,
        "site_id": camera.site_id,
        "site_name": site.name if site else camera.site_id,
        "status": camera.status,
        "snapshot_url": camera.snapshot_url,
        "stream_url": camera.stream_url,
        "last_seen": camera.last_seen.isoformat(),
        "last_seen_epoch": int(camera.last_seen.timestamp() * 1000),
    }


def build_site_master_data(db: Session, site_id: str) -> dict | None:
    site = db.get(Site, site_id)
    if site is None:
        return None

    now = utcnow()
    cameras = db.execute(
        select(Camera).where(Camera.site_id == site_id).order_by(Camera.last_seen.desc())
    ).scalars().all()
    alerts = db.execute(
        select(Alert).where(Alert.site_id == site_id).order_by(Alert.created_at.desc()).limit(8)
    ).scalars().all()
    visitors = db.execute(
        select(VisitorEvent)
        .where(VisitorEvent.site_id == site_id)
        .order_by(VisitorEvent.created_at.desc())
        .limit(8)
    ).scalars().all()
    actions = db.execute(
        select(RemoteAction)
        .where(RemoteAction.site_id == site_id)
        .order_by(RemoteAction.created_at.desc())
        .limit(8)
    ).scalars().all()
    open_alerts = sum(1 for alert in alerts if alert.status in ["open", "acknowledged"])
    active_cameras = sum(
        1
        for camera in cameras
        if camera.status == "online" and now - camera.last_seen <= timedelta(seconds=CAMERA_OFFLINE_SECONDS)
    )

    return {
        "generated_at": now.isoformat(),
        "site": {
            "site_id": site.id,
            "name": site.name,
            "address": site.address,
            "status": site.status,
            "last_seen": site.last_seen.isoformat(),
        },
        "kpis": {
            "active_cameras": active_cameras,
            "total_cameras": len(cameras),
            "open_alerts": open_alerts,
            "recent_visitors": len(visitors),
            "acciones_pendientes": sum(1 for action in actions if action.status in ["pending", "in_progress"]),
        },
        "live_mode": {
            "type": "snapshot-simulated",
            "title": "Vista pseudo-en-vivo de etapa 1",
            "description": (
                "Este prototipo refresca snapshots generados casi en tiempo real. "
                "El campo RTSP es un placeholder para una fase futura y todavia no se reproduce dentro del navegador."
            ),
        },
        "cameras": [camera_summary(camera) for camera in cameras],
        "latest_alerts": [alert_summary(alert) for alert in alerts],
        "latest_visitors": [visitor_summary(event) for event in visitors],
        "pending_visitors": [visitor_summary(event) for event in visitors if event.status == "pending"],
        "recent_actions": [action_summary(action) for action in actions],
    }


def sync_site_to_thingsboard(site_id: str) -> None:
    if not thingsboard_bridge.enabled:
        return

    try:
        with SessionLocal() as db:
            snapshot = build_site_snapshot(db, site_id)
            if snapshot is None:
                return
            thingsboard_bridge.publish_site(snapshot)
            thingsboard_bridge.publish_summary(build_dashboard_overview(db)["kpis"])
    except Exception as exc:
        print(f"thingsboard site sync failed for {site_id}: {exc}")


def sync_camera_to_thingsboard(camera_id: str) -> None:
    if not thingsboard_bridge.enabled:
        return

    try:
        with SessionLocal() as db:
            snapshot = build_camera_snapshot(db, camera_id)
            if snapshot is None:
                return
            thingsboard_bridge.publish_camera(snapshot)
    except Exception as exc:
        print(f"thingsboard camera sync failed for {camera_id}: {exc}")


def sync_all_to_thingsboard() -> None:
    try:
        if not thingsboard_bridge.bootstrap():
            return

        with SessionLocal() as db:
            sites = db.execute(select(Site).order_by(Site.id)).scalars().all()
            cameras = db.execute(select(Camera).order_by(Camera.id)).scalars().all()
            for site in sites:
                snapshot = build_site_snapshot(db, site.id)
                if snapshot is not None:
                    thingsboard_bridge.publish_site(snapshot)
            for camera in cameras:
                snapshot = build_camera_snapshot(db, camera.id)
                if snapshot is not None:
                    thingsboard_bridge.publish_camera(snapshot)
            thingsboard_bridge.publish_summary(build_dashboard_overview(db)["kpis"])
    except Exception as exc:
        print(f"thingsboard full sync failed: {exc}")


def run_monitor_pass() -> None:
    now = utcnow()
    site_threshold = now - timedelta(seconds=SITE_OFFLINE_SECONDS)
    camera_threshold = now - timedelta(seconds=CAMERA_OFFLINE_SECONDS)
    changes = False

    with SessionLocal() as db:
        sites = db.execute(select(Site)).scalars().all()
        cameras = db.execute(select(Camera)).scalars().all()

        for site in sites:
            edge_id = f"{site.id}-edge"
            if site.last_seen < site_threshold and site.status != "offline":
                site.status = "offline"
                ensure_alert(
                    db,
                    code="edge_offline",
                    site_id=site.id,
                    source_type="edge-agent",
                    source_id=edge_id,
                    severity="critical",
                    message=f"Se perdio el heartbeat del agente edge en {site.name}.",
                )
                changes = True
            elif site.status == "online":
                close_alerts(db, code="edge_offline", site_id=site.id, source_id=edge_id)

        for camera in cameras:
            if camera.last_seen < camera_threshold and camera.status != "offline":
                camera.status = "offline"
                ensure_alert(
                    db,
                    code="camera_offline",
                    site_id=camera.site_id,
                    source_type="camera",
                    source_id=camera.id,
                    severity="high",
                    message=f"{camera.name} esta fuera de linea o dejo de reportar.",
                )
                changes = True

        if changes:
            db.commit()
            live_hub.publish("dashboard.refresh", {"reason": "monitoring"})
            sync_all_to_thingsboard()
        else:
            db.rollback()


async def monitoring_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(run_monitor_pass)
        except Exception:
            pass
        await asyncio.sleep(MONITORING_INTERVAL_SECONDS)


async def thingsboard_sync_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(sync_all_to_thingsboard)
        except Exception:
            pass
        await asyncio.sleep(THINGSBOARD_SYNC_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    wait_for_dependencies()
    Base.metadata.create_all(bind=engine)
    monitoring_task = asyncio.create_task(monitoring_loop())
    thingsboard_task = asyncio.create_task(thingsboard_sync_loop())
    try:
        yield
    finally:
        monitoring_task.cancel()
        thingsboard_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitoring_task
        with contextlib.suppress(asyncio.CancelledError):
            await thingsboard_task


app.router.lifespan_context = lifespan


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/sites/{site_id}/master", response_class=HTMLResponse)
def site_master(request: Request, site_id: str, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="sitio no encontrado")
    return templates.TemplateResponse(
        "site_master.html",
        {"request": request, "site_id": site_id, "site_name": site.name},
    )


@app.get("/health")
def healthcheck():
    return {"status": "ok", "service": "backend-api", "timestamp": utcnow().isoformat()}


@app.get("/integrations/thingsboard")
def thingsboard_status():
    return thingsboard_bridge.status()


@app.get("/dashboard/overview")
def dashboard_overview(db: Session = Depends(get_db)):
    return build_dashboard_overview(db)


@app.get("/api/dashboard/overview")
def dashboard_overview_alias(db: Session = Depends(get_db)):
    return build_dashboard_overview(db)


@app.get("/dashboard/sites/{site_id}")
def dashboard_site_master(site_id: str, db: Session = Depends(get_db)):
    payload = build_site_master_data(db, site_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="sitio no encontrado")
    return payload


@app.websocket("/ws/live")
async def websocket_updates(websocket: WebSocket):
    await live_hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        await live_hub.disconnect(websocket)


@app.post("/sites/register")
def register_site(payload: SiteRegister, db: Session = Depends(get_db)):
    site = ensure_site(db, site_id=payload.id, site_name=payload.name, address=payload.address)
    db.commit()
    sync_site_to_thingsboard(payload.id)
    live_hub.publish("site.registered", {"site_id": site.id})
    return {
        "site_id": site.id,
        "name": site.name,
        "address": site.address,
        "status": site.status,
        "last_seen": site.last_seen.isoformat(),
    }


@app.get("/sites")
def list_sites(db: Session = Depends(get_db)):
    sites = db.execute(select(Site).order_by(Site.id)).scalars().all()
    return [
        {
            "site_id": site.id,
            "name": site.name,
            "address": site.address,
            "status": site.status,
            "last_seen": site.last_seen.isoformat(),
        }
        for site in sites
    ]


@app.get("/sites/{site_id}")
def get_site(site_id: str, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="sitio no encontrado")
    return {
        "site_id": site.id,
        "name": site.name,
        "address": site.address,
        "status": site.status,
        "last_seen": site.last_seen.isoformat(),
    }


@app.post("/heartbeat/site")
def site_heartbeat(payload: SiteHeartbeat, db: Session = Depends(get_db)):
    ensure_site(
        db,
        site_id=payload.site_id,
        site_name=payload.site_name,
        address=payload.address,
        status=payload.status,
    )
    edge_id = payload.edge_id or f"{payload.site_id}-edge"
    upsert_device(
        db,
        site_id=payload.site_id,
        device_id=edge_id,
        device_type="edge-agent",
        name="Agente Edge",
        status=payload.status,
    )
    if payload.status == "online":
        close_alerts(db, code="edge_offline", site_id=payload.site_id, source_id=edge_id)
    else:
        ensure_alert(
            db,
            code="edge_offline",
            site_id=payload.site_id,
            source_type="edge-agent",
            source_id=edge_id,
            severity="critical",
            message=f"El agente edge de {payload.site_id} reporto estado fuera de linea.",
        )
    db.commit()
    sync_site_to_thingsboard(payload.site_id)
    live_hub.publish("site.heartbeat", {"site_id": payload.site_id, "status": payload.status})
    return {"status": "accepted", "site_id": payload.site_id, "timestamp": utcnow().isoformat()}


@app.post("/heartbeat/device")
def device_heartbeat(payload: DeviceHeartbeat, db: Session = Depends(get_db)):
    ensure_site(db, site_id=payload.site_id)
    device = upsert_device(
        db,
        site_id=payload.site_id,
        device_id=payload.device_id,
        device_type=payload.device_type,
        name=payload.name,
        status=payload.status,
    )
    db.commit()
    sync_site_to_thingsboard(payload.site_id)
    live_hub.publish("device.heartbeat", {"device_id": device.id, "status": device.status})
    return {"status": "accepted", "device_id": device.id, "timestamp": utcnow().isoformat()}


@app.post("/cameras/status")
def update_camera_status(payload: CameraStatusUpdate, db: Session = Depends(get_db)):
    ensure_site(db, site_id=payload.site_id)
    upsert_device(
        db,
        site_id=payload.site_id,
        device_id=payload.camera_id,
        device_type="camera",
        name=payload.name,
        status=payload.status,
    )

    camera = db.get(Camera, payload.camera_id)
    if camera is None:
        camera = Camera(
            id=payload.camera_id,
            site_id=payload.site_id,
            name=payload.name,
            status=payload.status,
            stream_url=payload.stream_url,
            last_seen=utcnow(),
        )
        db.add(camera)
    else:
        camera.site_id = payload.site_id
        camera.name = payload.name
        camera.status = payload.status
        camera.stream_url = payload.stream_url
        camera.last_seen = utcnow()

    if payload.generate_snapshot:
        label = payload.snapshot_label or payload.name
        camera.snapshot_url = media_store.create_placeholder(
            db,
            category="camera",
            title=label,
            subtitle=f"Snapshot de camara en {payload.site_id}",
            footer_lines=[
                f"Camara ID: {payload.camera_id}",
                f"Estado: {payload.status}",
                f"Visto: {utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            ],
            accent="#33d0b5",
            site_id=payload.site_id,
            camera_id=payload.camera_id,
            description=f"Snapshot de {payload.camera_id}",
        )

    if payload.status == "offline":
        ensure_alert(
            db,
            code="camera_offline",
            site_id=payload.site_id,
            source_type="camera",
            source_id=payload.camera_id,
            severity="high",
            message=f"{payload.name} reporto estado fuera de linea.",
        )
    else:
        close_alerts(db, code="camera_offline", site_id=payload.site_id, source_id=payload.camera_id)

    db.commit()
    sync_camera_to_thingsboard(payload.camera_id)
    sync_site_to_thingsboard(payload.site_id)
    live_hub.publish("camera.status", {"camera_id": payload.camera_id, "status": payload.status})
    return camera_summary(camera)


@app.get("/cameras")
def list_cameras(site_id: str | None = Query(default=None), db: Session = Depends(get_db)):
    query = select(Camera).order_by(Camera.last_seen.desc())
    if site_id:
        query = query.where(Camera.site_id == site_id)
    cameras = db.execute(query).scalars().all()
    return [camera_summary(camera) for camera in cameras]


@app.get("/cameras/{camera_id}")
def get_camera(camera_id: str, db: Session = Depends(get_db)):
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="camara no encontrada")
    return camera_summary(camera)


@app.post("/visitors/checkin")
def create_visitor_checkin(payload: VisitorCheckin, db: Session = Depends(get_db)):
    ensure_site(db, site_id=payload.site_id)
    snapshot_url = media_store.create_placeholder(
        db,
        category="visitor",
        title=payload.visitor_name,
        subtitle=f"Verificacion de visitante en {payload.site_id}",
        footer_lines=[
            f"Unidad: {payload.unit_to_visit}",
            f"Residente: {payload.host_name}",
            f"Estado: {payload.status}",
        ],
        accent="#f39c5a",
        site_id=payload.site_id,
        description=f"Snapshot de visitante para {payload.visitor_name}",
    )
    event = VisitorEvent(
        id=uuid.uuid4().hex,
        site_id=payload.site_id,
        visitor_name=payload.visitor_name,
        unit_to_visit=payload.unit_to_visit,
        host_name=payload.host_name,
        id_type=payload.id_type,
        snapshot_url=snapshot_url,
        status=payload.status,
        notes=payload.notes,
    )
    db.add(event)

    if payload.status == "denied":
        ensure_alert(
            db,
            code="denied_access",
            site_id=payload.site_id,
            source_type="visitor",
            source_id=event.id,
            severity="high",
            message=f"Intento de acceso denegado para {payload.visitor_name}.",
        )
    elif payload.status == "pending":
        ensure_alert(
            db,
            code="visitor_review",
            site_id=payload.site_id,
            source_type="visitor",
            source_id=event.id,
            severity="medium",
            message=f"El visitante {payload.visitor_name} queda pendiente de revision operativa.",
        )

    db.commit()
    sync_site_to_thingsboard(payload.site_id)
    live_hub.publish("visitor.checkin", {"event_id": event.id, "site_id": payload.site_id})
    return visitor_summary(event)


@app.get("/visitors/events")
def list_visitor_events(
    site_id: str | None = Query(default=None),
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db),
):
    query = select(VisitorEvent).order_by(VisitorEvent.created_at.desc()).limit(limit)
    if site_id:
        query = query.where(VisitorEvent.site_id == site_id)
    events = db.execute(query).scalars().all()
    return [visitor_summary(event) for event in events]


@app.get("/visitors/events/{event_id}")
def get_visitor_event(event_id: str, db: Session = Depends(get_db)):
    event = db.get(VisitorEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="evento de visitante no encontrado")
    return visitor_summary(event)


@app.post("/visitors/events/{event_id}/decision")
def decide_visitor_event(event_id: str, payload: VisitorDecision, db: Session = Depends(get_db)):
    event = db.get(VisitorEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="evento de visitante no encontrado")

    decision = payload.decision.lower()
    if decision not in ["approved", "denied"]:
        raise HTTPException(status_code=400, detail="la decision debe ser approved o denied")

    event.status = decision
    event.notes = f"{payload.operator_name}: {'Acceso aprobado' if decision == 'approved' else 'Acceso denegado'}"
    close_alerts(db, code="visitor_review", site_id=event.site_id, source_id=event.id)

    created_action = None
    if decision == "denied":
        ensure_alert(
            db,
            code="denied_access",
            site_id=event.site_id,
            source_type="visitor",
            source_id=event.id,
            severity="high",
            message=f"Acceso denegado para {event.visitor_name}.",
        )
    elif payload.trigger_remote_action:
        created_action = create_remote_action(
            db,
            site_id=event.site_id,
            action_type="door_control",
            target_id=f"{event.site_id}-main-gate",
            command="open_door",
            requested_by=payload.operator_name,
            payload={
                "motivo": f"Aprobacion de visitante {event.visitor_name}",
                "visitor_event_id": event.id,
                "unit_to_visit": event.unit_to_visit,
            },
        )

    db.commit()
    sync_site_to_thingsboard(event.site_id)
    live_hub.publish(
        "visitor.decision",
        {
            "event_id": event.id,
            "site_id": event.site_id,
            "decision": event.status,
            "action_id": created_action.id if created_action else None,
        },
    )
    return {
        "visitor_event": visitor_summary(event),
        "remote_action": action_summary(created_action) if created_action else None,
    }


@app.post("/sites/{site_id}/actions")
def create_site_action(site_id: str, payload: RemoteActionCreate, db: Session = Depends(get_db)):
    ensure_site(db, site_id=site_id)
    action = create_remote_action(
        db,
        site_id=site_id,
        action_type=payload.action_type,
        target_id=payload.target_id,
        command=payload.command,
        requested_by=payload.requested_by,
        payload=payload.payload,
    )
    db.commit()
    sync_site_to_thingsboard(site_id)
    live_hub.publish("remote_action.created", {"site_id": site_id, "action_id": action.id})
    return action_summary(action)


@app.get("/sites/{site_id}/actions")
def list_site_actions(
    site_id: str,
    limit: int = Query(default=20, le=100),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = select(RemoteAction).where(RemoteAction.site_id == site_id).order_by(RemoteAction.created_at.desc()).limit(limit)
    if status:
        query = query.where(RemoteAction.status == status)
    actions = db.execute(query).scalars().all()
    return [action_summary(action) for action in actions]


@app.get("/sites/{site_id}/actions/pending")
def list_pending_site_actions(site_id: str, db: Session = Depends(get_db)):
    actions = db.execute(
        select(RemoteAction)
        .where(RemoteAction.site_id == site_id, RemoteAction.status == "pending")
        .order_by(RemoteAction.created_at.asc())
    ).scalars().all()
    return [action_summary(action) for action in actions]


@app.post("/sites/{site_id}/actions/{action_id}/status")
def update_site_action_status(
    site_id: str,
    action_id: str,
    payload: RemoteActionStatusUpdate,
    db: Session = Depends(get_db),
):
    action = db.get(RemoteAction, action_id)
    if action is None or action.site_id != site_id:
        raise HTTPException(status_code=404, detail="accion remota no encontrada")

    status = payload.status.lower()
    if status not in ["pending", "in_progress", "completed", "failed"]:
        raise HTTPException(status_code=400, detail="estado de accion invalido")

    action.status = status
    action.result_message = payload.result_message
    if status == "in_progress":
        action.started_at = utcnow()
    if status in ["completed", "failed"]:
        if action.started_at is None:
            action.started_at = utcnow()
        action.completed_at = utcnow()
        if action.command == "open_door" and status == "completed":
            ensure_alert(
                db,
                code="remote_door_opened",
                site_id=site_id,
                source_type="remote-action",
                source_id=action.id,
                severity="low",
                message=f"Puerta principal abierta de forma remota por {action.requested_by}.",
            )
        elif status == "failed":
            ensure_alert(
                db,
                code="remote_action_failed",
                site_id=site_id,
                source_type="remote-action",
                source_id=action.id,
                severity="medium",
                message=f"Fallo la accion remota {action.command} para {action.target_id}.",
            )

    db.commit()
    sync_site_to_thingsboard(site_id)
    live_hub.publish(
        "remote_action.updated",
        {"site_id": site_id, "action_id": action.id, "status": action.status},
    )
    return action_summary(action)


@app.post("/alerts")
def create_alert(payload: AlertCreate, db: Session = Depends(get_db)):
    ensure_site(db, site_id=payload.site_id)
    alert = ensure_alert(
        db,
        code=payload.code,
        site_id=payload.site_id,
        source_type=payload.source_type,
        source_id=payload.source_id,
        severity=payload.severity,
        message=payload.message,
        status=payload.status,
    )
    db.commit()
    sync_site_to_thingsboard(payload.site_id)
    live_hub.publish("alert.created", {"alert_id": alert.id, "site_id": payload.site_id})
    return alert_summary(alert)


@app.get("/alerts")
def list_alerts(
    site_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db),
):
    query = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    if site_id:
        query = query.where(Alert.site_id == site_id)
    if status:
        query = query.where(Alert.status == status)
    alerts = db.execute(query).scalars().all()
    return [alert_summary(alert) for alert in alerts]


@app.post("/alerts/{alert_id}/ack")
def acknowledge_alert(alert_id: str, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alerta no encontrada")
    alert.status = "acknowledged"
    alert.acknowledged_at = utcnow()
    db.commit()
    sync_site_to_thingsboard(alert.site_id)
    live_hub.publish("alert.acknowledged", {"alert_id": alert.id})
    return alert_summary(alert)


@app.post("/media/upload")
def upload_media(
    file: UploadFile = File(...),
    category: str = Query(default="general"),
    site_id: str | None = Query(default=None),
    camera_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="archivo vacio")
    url = media_store.upload_file(
        db,
        content=content,
        filename=file.filename or "asset.bin",
        content_type=file.content_type or "application/octet-stream",
        category=category,
        site_id=site_id,
        camera_id=camera_id,
        description=f"Uploaded asset {file.filename}",
    )
    db.commit()
    return {"url": url, "filename": file.filename, "content_type": file.content_type}


@app.get("/media/{media_id}")
def get_media(media_id: str, db: Session = Depends(get_db)):
    try:
        asset, content = media_store.fetch_asset(media_id, db)
    except KeyError:
        raise HTTPException(status_code=404, detail="media no encontrada") from None
    return Response(content=content, media_type=asset.content_type)
