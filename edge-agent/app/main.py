import os
import random
import time

import requests


BACKEND_URL = os.getenv("BACKEND_URL", "http://backend-api:8000")
SITE_ID = os.getenv("SITE_ID", "condo-01")
SITE_NAME = os.getenv("SITE_NAME", SITE_ID.replace("-", " ").title())
SITE_ADDRESS = os.getenv("SITE_ADDRESS", "Condominio demo")
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "8"))

# Futuro edge real:
# - montar un inventario local como /app/config/devices.condo-01.yaml
# - leer desde DEVICE_CONFIG_PATH antes de registrar dispositivos fisicos
# - mapear target_id y command contra ese inventario local
DEVICE_CONFIG_PATH = os.getenv("DEVICE_CONFIG_PATH", "/app/config/devices.condo-01.yaml")

session = requests.Session()
random.seed(SITE_ID)


def post_json(path: str, payload: dict) -> dict | None:
    url = f"{BACKEND_URL}{path}"
    try:
        response = session.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print(f"evento enviado {path} para {SITE_ID}: {response.status_code}")
        if response.content:
            return response.json()
        return None
    except requests.RequestException as exc:
        print(f"fallo al llamar {url}: {exc}")
        return None


def get_json(path: str) -> list[dict]:
    url = f"{BACKEND_URL}{path}"
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return data
        return []
    except requests.RequestException as exc:
        print(f"fallo al consultar {url}: {exc}")
        return []


def register_site() -> None:
    # Punto futuro de integracion:
    # despues de registrar el sitio, aqui se puede cargar DEVICE_CONFIG_PATH
    # y registrar camaras, puertas y sensores fisicos descubiertos en la LAN local.
    post_json(
        "/sites/register",
        {"id": SITE_ID, "name": SITE_NAME, "address": SITE_ADDRESS},
    )


def heartbeat() -> None:
    edge_id = f"{SITE_ID}-edge"
    post_json(
        "/heartbeat/site",
        {
            "site_id": SITE_ID,
            "site_name": SITE_NAME,
            "address": SITE_ADDRESS,
            "status": "online",
            "edge_id": edge_id,
        },
    )
    post_json(
        "/heartbeat/device",
        {
            "site_id": SITE_ID,
            "device_id": edge_id,
            "device_type": "edge-agent",
            "name": "Agente Edge",
            "status": "online",
        },
    )


def maybe_trigger_alert() -> None:
    chance = random.random()
    if chance < 0.08:
        post_json(
            "/alerts",
            {
                "site_id": SITE_ID,
                "source_type": "door",
                "source_id": f"{SITE_ID}-main-gate",
                "severity": "critical",
                "message": f"Puerta forzada detectada en {SITE_NAME}.",
                "code": "door_forced_open",
            },
        )
    elif chance < 0.16:
        post_json(
            "/alerts",
            {
                "site_id": SITE_ID,
                "source_type": "motion-zone",
                "source_id": f"{SITE_ID}-parking-lot",
                "severity": "medium",
                "message": f"Movimiento detectado fuera de horario en {SITE_NAME}.",
                "code": "after_hours_motion",
            },
        )


def update_action_status(action_id: str, status: str, result_message: str) -> None:
    post_json(
        f"/sites/{SITE_ID}/actions/{action_id}/status",
        {"status": status, "result_message": result_message},
    )


def execute_remote_action(action: dict) -> None:
    action_id = action["action_id"]
    command = action["command"]
    target_id = action["target_id"]
    print(f"ejecutando accion remota {command} para {target_id} en {SITE_ID}")
    update_action_status(action_id, "in_progress", "Comando recibido por el edge-agent")
    time.sleep(2)

    # Punto futuro de integracion con hardware real:
    # 1. leer DEVICE_CONFIG_PATH
    # 2. buscar el dispositivo por target_id
    # 3. despachar a un driver real segun controller_type o protocol
    # 4. confirmar resultado con sensor o respuesta del controlador
    # 5. reportar completed o failed al backend
    if command == "open_door":
        update_action_status(action_id, "completed", "Puerta principal liberada durante 5 segundos")
    elif command == "toggle_lobby_light":
        update_action_status(action_id, "completed", "Luz del lobby activada de forma remota")
    else:
        update_action_status(action_id, "failed", f"Comando no soportado por el edge-agent: {command}")


def poll_remote_actions() -> None:
    # Punto futuro de integracion:
    # aqui puedes filtrar acciones que no existan en DEVICE_CONFIG_PATH
    # para no ejecutar comandos sobre dispositivos no inventariados localmente.
    actions = get_json(f"/sites/{SITE_ID}/actions/pending")
    for action in actions:
        execute_remote_action(action)


def main() -> None:
    register_site()
    cycle = 0
    while True:
        cycle += 1
        if cycle % 10 == 0:
            downtime = HEARTBEAT_INTERVAL + 42
            print(f"simulando pausa del edge-agent para {SITE_ID} durante {downtime}s")
            time.sleep(downtime)
            continue

        heartbeat()
        maybe_trigger_alert()
        poll_remote_actions()
        time.sleep(HEARTBEAT_INTERVAL)


if __name__ == "__main__":
    main()
