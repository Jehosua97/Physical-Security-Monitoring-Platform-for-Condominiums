# Physical Security Monitoring Platform for Condominiums

Prototipo etapa 1 para una plataforma centralizada de monitoreo de seguridad fisica y gestion de visitantes. El stack corre en Docker y simula tres condominios remotos enviando eventos a un centro de operaciones.

## Que incluye este MVP

- Backend FastAPI para sitios, camaras, visitantes, alertas, medios y acciones remotas
- PostgreSQL para datos operativos
- MinIO para snapshots y evidencias
- Mosquitto como base opcional para fases futuras con MQTT
- ThingsBoard como capa de telemetria y tablero operacional complementario
- Dashboard web principal integrado en el backend para la demo diaria
- MediaMTX por condominio para:
  - WebRTC en vivo
  - LL-HLS como fallback y reproduccion en navegador
  - playback historico de segmentos grabados
- Tres sitios simulados:
  - `condo-01`
  - `condo-02`
  - `condo-03`
- Por cada sitio:
  - heartbeat del edge-agent
  - camaras simuladas con video en vivo
  - eventos de visitante
  - alertas simuladas
  - ejecucion remota simulada de comandos como abrir puerta o activar luz

## Inicio rapido

```bash
docker compose up --build
```

## URLs principales

- Panel operativo principal: `http://localhost:8000/`
- Vista maestra por condominio: `http://localhost:8000/sites/condo-01/master`
- Documentacion API: `http://localhost:8000/docs`
- ThingsBoard: `http://localhost:9090`
- Consola MinIO: `http://localhost:9001`
- Credenciales MinIO: `minioadmin / minioadmin`

## URLs de video por sitio

- `condo-01`
  - WebRTC: `http://localhost:8889/condo-01/condo-01-cam-lobby`
  - LL-HLS: `http://localhost:8888/condo-01/condo-01-cam-lobby`
  - Playback API: `http://localhost:9996/list?path=condo-01%2Fcondo-01-cam-lobby`
- `condo-02`
  - WebRTC: `http://localhost:8899/condo-02/condo-02-cam-lobby`
  - LL-HLS: `http://localhost:8898/condo-02/condo-02-cam-lobby`
  - Playback API: `http://localhost:9997/list?path=condo-02%2Fcondo-02-cam-lobby`
- `condo-03`
  - WebRTC: `http://localhost:8909/condo-03/condo-03-cam-garage`
  - LL-HLS: `http://localhost:8908/condo-03/condo-03-cam-garage`
  - Playback API: `http://localhost:9998/list?path=condo-03%2Fcondo-03-cam-garage`

## Que hace cada interfaz

- `localhost:8000`
  - Es la aplicacion operativa del demo.
  - Aqui se ven los condominios, visitantes, video en vivo, playback, alertas y controles remotos.
  - Desde la vista maestra de cada condominio se aprueban visitantes y se envian comandos al edge-agent.
- `localhost:9090`
  - Es ThingsBoard.
  - Aqui vive la capa de telemetria, dispositivos y dashboard operacional.
  - En esta etapa no es donde se atienden las aprobaciones ni donde se ejecutan los controles remotos del demo.

## Como funciona el flujo operativo

1. Los simuladores de cada condominio publican heartbeats, video simulado, snapshots, visitantes y alertas al backend.
2. Cada sitio tiene un `MediaMTX` local que transforma la senal RTSP simulada en WebRTC, LL-HLS y playback historico.
3. El backend guarda la operacion en PostgreSQL y publica snapshots a MinIO.
4. El panel en `localhost:8000` muestra la operacion en tiempo real y permite abrir cada camara en grande.
5. Cuando un visitante queda `pending`, el operador central decide si aprobar o denegar.
6. Si el operador aprueba con apertura, el backend crea una accion remota pendiente.
7. El edge-agent del condominio consulta acciones pendientes y ejecuta la simulacion.
8. El edge-agent reporta el resultado al backend y la vista maestra refleja el estado final.
9. ThingsBoard recibe la telemetria sincronizada como capa adicional de monitoreo.

## Como reemplazar la simulacion por una camara real

1. Quita el servicio `stream-publisher-condo-XX` del `docker-compose.yml`.
2. Abre `infra/mediamtx/condo-XX.yml`.
3. Cambia el `source: publisher` de la ruta de la camara por un `source: rtsp://usuario:password@IP/stream`.
4. Opcionalmente reemplaza `camera-sim` por un collector real que descubra ONVIF, haga snapshots reales y reporte heartbeat desde la LAN del condominio.
5. Si el edge fisico va a controlar puertas o luces, centraliza ese inventario en `edge-agent/config/devices.condo-01.yaml`.

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
|-- stream-publisher/
|-- infra/
`-- docs/
```
