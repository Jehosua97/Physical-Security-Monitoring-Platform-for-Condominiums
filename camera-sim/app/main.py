import os
import random
import time

import requests


BACKEND_URL = os.getenv("BACKEND_URL", "http://backend-api:8000")
SITE_ID = os.getenv("SITE_ID", "condo-01")
CAMERA_IDS = [item.strip() for item in os.getenv("CAMERA_IDS", "cam-01,cam-02").split(",")]
CAMERA_NAMES = [item.strip() for item in os.getenv("CAMERA_NAMES", "Camara lobby,Camara acceso").split(",")]
STREAM_BASE_URL = os.getenv("STREAM_BASE_URL", "rtsp://mediamtx:8554/default")
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL_SECONDS", "9"))

session = requests.Session()
random.seed(f"{SITE_ID}-cameras")


def post_json(path: str, payload: dict) -> None:
    url = f"{BACKEND_URL}{path}"
    try:
        response = session.post(url, json=payload, timeout=12)
        response.raise_for_status()
        print(f"actualizacion de camara aceptada para {payload.get('camera_id')}")
    except requests.RequestException as exc:
        print(f"fallo al llamar {url}: {exc}")


def camera_name(index: int) -> str:
    if index < len(CAMERA_NAMES):
        return CAMERA_NAMES[index]
    return f"Camara {index + 1}"


def camera_status(index: int, cycle: int) -> str:
    if SITE_ID == "condo-03" and index == 1 and cycle % 5 == 0:
        return "offline"
    if random.random() < 0.06:
        return "offline"
    return "online"


def main() -> None:
    cycle = 0
    while True:
        cycle += 1
        for index, camera_id in enumerate(CAMERA_IDS):
            name = camera_name(index)
            status = camera_status(index, cycle)
            # En el demo, stream_url apunta a la ruta RTSP de ingreso en MediaMTX dentro de Docker.
            # Cuando conectes una camara real, este camera_id puede mantenerse igual; el cambio real
            # ocurre en el edge:
            # 1. reemplaza el publisher simulado por un source RTSP/ONVIF real en infra/mediamtx/<site>.yml
            # 2. o sustituye este servicio por un collector que descubra camaras fisicas y reporte
            #    heartbeat, snapshots y metadata desde la LAN del condominio.
            payload = {
                "site_id": SITE_ID,
                "camera_id": camera_id,
                "name": name,
                "status": status,
                "stream_url": f"{STREAM_BASE_URL}/{camera_id}",
                "generate_snapshot": True,
                "snapshot_label": f"{name} - {SITE_ID}",
            }
            post_json("/cameras/status", payload)
        time.sleep(UPDATE_INTERVAL)


if __name__ == "__main__":
    main()
