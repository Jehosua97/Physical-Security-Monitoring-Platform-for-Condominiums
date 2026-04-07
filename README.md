# Physical Security Monitoring Platform for Condominiums

Prototipo etapa 1 para una plataforma centralizada de monitoreo de seguridad física y gestión de visitantes. El stack corre en Docker y simula tres condominios remotos enviando eventos a un centro de operaciones.

## Qué incluye este MVP

- Backend FastAPI para sitios, cámaras, visitantes, alertas, medios y acciones remotas
- PostgreSQL para datos operativos
- MinIO para snapshots y evidencias
- Mosquitto como base opcional para fases futuras con MQTT
- ThingsBoard como capa de telemetría y tablero operacional complementario
- Dashboard web principal integrado en el backend para la demo diaria
- Tres sitios simulados:
  - `condo-01`
  - `condo-02`
  - `condo-03`
- Por cada sitio:
  - heartbeat del edge-agent
  - cámaras simuladas con snapshots
  - eventos de visitante
  - alertas simuladas
  - ejecución remota simulada de comandos como abrir puerta o activar luz

## Inicio rápido

```bash
docker compose up --build
```

## URLs principales

- Panel operativo principal: `http://localhost:8000/`
- Vista maestra por condominio: `http://localhost:8000/sites/condo-01/master`
- Documentación API: `http://localhost:8000/docs`
- ThingsBoard: `http://localhost:9090`
- Consola MinIO: `http://localhost:9001`
- Credenciales MinIO: `minioadmin / minioadmin`

## Qué hace cada interfaz

- `localhost:8000`
  - Es la aplicación operativa del demo.
  - Aquí se ven los condominios, visitantes, snapshots, alertas y controles remotos.
  - Desde la vista maestra de cada condominio se aprueban visitantes y se envían comandos al edge-agent.
- `localhost:9090`
  - Es ThingsBoard.
  - Aquí vive la capa de telemetría, dispositivos y dashboard operacional.
  - En esta etapa no es donde se atienden las aprobaciones ni donde se ejecutan los controles remotos del demo.

## Cómo funciona el flujo operativo

1. Los simuladores de cada condominio publican heartbeats, snapshots, visitantes y alertas al backend.
2. El backend guarda la operación en PostgreSQL y publica snapshots a MinIO.
3. El panel en `localhost:8000` muestra la operación en tiempo real.
4. Cuando un visitante queda `pending`, el operador central decide si aprobar o denegar.
5. Si el operador aprueba con apertura, el backend crea una acción remota pendiente.
6. El edge-agent del condominio consulta acciones pendientes y ejecuta la simulación.
7. El edge-agent reporta el resultado al backend y la vista maestra refleja el estado final.
8. ThingsBoard recibe la telemetría sincronizada como capa adicional de monitoreo.

## Nota importante sobre streaming

- La etapa 1 no reproduce video en vivo dentro del navegador.
- La experiencia actual es pseudo-en-vivo mediante snapshots actualizados periódicamente.
- Los `stream_url` visibles son placeholders para una fase futura con HLS, WebRTC o MJPEG.

## Endpoints principales

- `POST /sites/register`
- `GET /sites`
- `POST /heartbeat/site`
- `POST /heartbeat/device`
- `POST /cameras/status`
- `GET /cameras`
- `POST /visitors/checkin`
- `GET /visitors/events`
- `POST /visitors/events/{event_id}/decision`
- `POST /sites/{site_id}/actions`
- `GET /sites/{site_id}/actions`
- `POST /sites/{site_id}/actions/{action_id}/status`
- `POST /alerts`
- `GET /alerts`
- `POST /alerts/{alert_id}/ack`
- `POST /media/upload`
- `GET /media/{id}`

## Estructura del proyecto

```text
.
|-- docker-compose.yml
|-- .env
|-- backend/
|-- edge-agent/
|-- camera-sim/
|-- visitor-sim/
|-- infra/
`-- docs/
```
