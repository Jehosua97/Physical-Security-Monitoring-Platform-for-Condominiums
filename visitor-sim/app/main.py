import os
import random
import time

import requests


BACKEND_URL = os.getenv("BACKEND_URL", "http://backend-api:8000")
SITE_ID = os.getenv("SITE_ID", "condo-01")
VISITOR_INTERVAL = int(os.getenv("VISITOR_INTERVAL_SECONDS", "18"))

VISITORS = [
    "Maria Santos",
    "Diego Ramos",
    "Elena Castillo",
    "Victor Paredes",
    "Nora Valdez",
    "Sofia Herrera",
    "Luis Benitez",
    "Carla Medina",
]
HOSTS = [
    "Alicia Gomez",
    "Daniel Torres",
    "Marcela Rios",
    "Kevin Duarte",
    "Paula Jimenez",
]
UNITS = ["A-101", "A-204", "B-302", "C-110", "PH-02"]
ID_TYPES = ["Cedula nacional", "Pasaporte", "Referencia del residente", "Credencial de mensajeria"]

session = requests.Session()
random.seed(f"{SITE_ID}-visitors")


def post_json(path: str, payload: dict) -> None:
    url = f"{BACKEND_URL}{path}"
    try:
        response = session.post(url, json=payload, timeout=12)
        response.raise_for_status()
        print(f"evento de visitante aceptado para {payload.get('visitor_name')}")
    except requests.RequestException as exc:
        print(f"fallo al llamar {url}: {exc}")


def visitor_status() -> str:
    roll = random.random()
    if SITE_ID == "condo-02" and roll < 0.18:
        return "pending"
    if roll < 0.72:
        return "approved"
    if roll < 0.9:
        return "pending"
    return "denied"


def build_event() -> dict:
    status = visitor_status()
    visitor_name = random.choice(VISITORS)
    host_name = random.choice(HOSTS)
    unit_to_visit = random.choice(UNITS)
    id_type = random.choice(ID_TYPES)
    notes = "Visita rutinaria"

    if status == "denied":
        id_type = "Documento no reconocido"
        notes = "Se recomienda escalar con el guardia"
    elif status == "pending":
        notes = "Esperando confirmacion del residente"

    return {
        "site_id": SITE_ID,
        "visitor_name": visitor_name,
        "unit_to_visit": unit_to_visit,
        "host_name": host_name,
        "id_type": id_type,
        "status": status,
        "notes": notes,
    }


def main() -> None:
    while True:
        post_json("/visitors/checkin", build_event())
        time.sleep(VISITOR_INTERVAL)


if __name__ == "__main__":
    time.sleep(6)
    main()
