const state = {
  socket: null,
  camerasById: new Map(),
};

const STATUS_LABELS = {
  online: "En linea",
  offline: "Fuera de linea",
  approved: "Aprobado",
  pending: "Pendiente",
  denied: "Denegado",
  open: "Abierta",
  acknowledged: "Reconocida",
  closed: "Cerrada",
  low: "Baja",
  medium: "Media",
  high: "Alta",
  critical: "Critica",
};

function formatTime(value) {
  if (!value) {
    return "Sin datos aun";
  }

  return new Intl.DateTimeFormat("es-CO", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function translateStatus(value) {
  return STATUS_LABELS[value] || value || "Sin estado";
}

function statusClass(status) {
  return `status-pill status-${(status || "unknown").toLowerCase()}`;
}

function renderKpis(kpis) {
  const items = [
    ["Sitios en linea", `${kpis.sites_online}/${kpis.sites_total}`],
    ["Camaras en linea", `${kpis.cameras_online}`],
    ["Eventos de visitantes", `${kpis.visitors_total}`],
    ["Alertas abiertas", `${kpis.alerts_open}`],
    ["Operacion remota", "WebRTC + LL-HLS + playback"],
  ];

  document.getElementById("kpi-grid").innerHTML = items
    .map(
      ([title, value]) => `
        <article class="kpi-card">
          <p class="kpi-title">${title}</p>
          <p class="kpi-value">${value}</p>
        </article>
      `
    )
    .join("");
}

function renderSites(sites) {
  const container = document.getElementById("site-grid");
  if (!sites.length) {
    container.innerHTML =
      '<div class="empty-state">Esperando el registro inicial de los edge-agents de cada condominio.</div>';
    return;
  }

  container.innerHTML = sites
    .map(
      (site) => `
        <article class="site-card">
          ${
            site.latest_snapshot_url
              ? `<img class="site-preview" src="${site.latest_snapshot_url}" alt="Vista previa de ${site.name}" />`
              : '<div class="site-preview"></div>'
          }
          <div class="site-body">
            <div class="site-topline">
              <div>
                <h3>${site.name}</h3>
                <p class="site-address">${site.site_id}</p>
              </div>
              <span class="${statusClass(site.status)}">${translateStatus(site.status)}</span>
            </div>
            <p class="site-address">${site.address}</p>
            <div class="site-metrics">
              <span class="metric-chip">${site.active_cameras} camaras activas</span>
              <span class="metric-chip">${site.recent_visitors} visitantes recientes</span>
              <span class="metric-chip">${site.recent_alerts} alertas abiertas</span>
              <span class="metric-chip">Ultima senal ${formatTime(site.last_seen)}</span>
            </div>
            <div class="site-actions">
              <a class="site-link" href="/sites/${site.site_id}/master">Abrir vista maestra</a>
            </div>
          </div>
        </article>
      `
    )
    .join("");
}

function renderFeed(containerId, items, kind) {
  const container = document.getElementById(containerId);
  if (!items.length) {
    const messages = {
      alerts: "Sin alertas todavia. Los simuladores siguen calentando.",
      visitors: "Sin visitantes todavia. Los simuladores siguen calentando.",
    };
    container.innerHTML = `<div class="empty-state">${messages[kind] || "Sin datos aun."}</div>`;
    return;
  }

  container.innerHTML = items
    .map((item) => {
      if (kind === "alerts") {
        return `
          <article class="feed-card">
            <div class="feed-topline">
              <p class="feed-title">${item.message}</p>
              <span class="${statusClass(item.severity)}">${translateStatus(item.severity)}</span>
            </div>
            <p class="feed-meta">${item.site_id} · ${item.source_type} ${item.source_id}</p>
            <div class="feed-badge-row">
              <span class="metric-chip">${translateStatus(item.status)}</span>
              <span class="metric-chip">${formatTime(item.timestamp)}</span>
            </div>
          </article>
        `;
      }

      return `
        <article class="feed-card">
          <div class="feed-topline">
            <p class="feed-title">${item.visitor_name}</p>
            <span class="${statusClass(item.status)}">${translateStatus(item.status)}</span>
          </div>
          <p class="feed-meta">${item.site_id} · Unidad ${item.unit_to_visit} · Residente ${item.host_name}</p>
          <div class="feed-badge-row">
            <span class="metric-chip">${item.id_type}</span>
            <span class="metric-chip">${formatTime(item.timestamp)}</span>
          </div>
        </article>
      `;
    })
    .join("");
}

function cameraActionButtons(camera) {
  return `
    <div class="camera-card-actions">
      <button class="action-button" type="button" data-camera-open="${camera.camera_id}" data-camera-mode="webrtc">
        Ver en vivo
      </button>
      <button
        class="action-button action-button-secondary"
        type="button"
        data-camera-open="${camera.camera_id}"
        data-camera-mode="playback"
      >
        Reproducir
      </button>
      <a class="site-link" href="/sites/${camera.site_id}/master">Ir al condo</a>
    </div>
  `;
}

function cameraPreviewOverlay(camera, label = "Abrir en grande") {
  return `
    <button
      class="camera-preview-hitbox"
      type="button"
      data-camera-open="${camera.camera_id}"
      data-camera-mode="webrtc"
      aria-label="Abrir ${camera.name} en vista ampliada"
      title="Abrir ${camera.name} en vista ampliada"
    >
      <span class="camera-preview-chip">En vivo</span>
      <span class="camera-preview-chip camera-preview-chip-strong">${label}</span>
    </button>
  `;
}

function renderCameras(cameras) {
  const container = document.getElementById("camera-grid");
  state.camerasById = new Map(cameras.map((camera) => [camera.camera_id, camera]));

  if (!cameras.length) {
    container.innerHTML =
      '<div class="empty-state">Las camaras simuladas todavia estan enviando sus primeros streams.</div>';
    return;
  }

  container.innerHTML = cameras
    .map(
      (camera) => `
        <article class="camera-card camera-card-live">
          <div class="camera-card-media">
            ${window.CameraExperience.buildCameraViewport(camera, { compact: true })}
            ${cameraPreviewOverlay(camera)}
          </div>
          <div class="camera-body">
            <div class="site-topline">
              <div>
                <h3>${camera.name}</h3>
                <p class="site-address">${camera.site_id} · ${camera.camera_id}</p>
              </div>
              <span class="${statusClass(camera.status)}">${translateStatus(camera.status)}</span>
            </div>
            <div class="feed-badge-row">
              <span class="metric-chip">WebRTC vivo</span>
              <span class="metric-chip">LL-HLS fallback</span>
              <span class="metric-chip">Ultima senal ${formatTime(camera.last_seen)}</span>
            </div>
            <p class="camera-note">${camera.media?.notes || "Camara lista para abrir en vivo o reproducir."}</p>
            ${cameraActionButtons(camera)}
          </div>
        </article>
      `
    )
    .join("");
}

async function loadOverview() {
  const response = await fetch("/dashboard/overview", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`No fue posible cargar el dashboard: ${response.status}`);
  }

  const data = await response.json();
  renderKpis(data.kpis);
  renderSites(data.sites);
  renderFeed("alerts-list", data.latest_alerts, "alerts");
  renderFeed("visitors-list", data.latest_visitors, "visitors");
  renderCameras(data.latest_cameras);
  document.getElementById("generated-at").textContent = `Vista actualizada ${formatTime(data.generated_at)}`;
}

function openCameraFromButton(button) {
  const cameraId = button.dataset.cameraOpen;
  const preferredMode = button.dataset.cameraMode || "webrtc";
  const camera = state.camerasById.get(cameraId);
  if (camera) {
    window.CameraExperience.openCamera(camera, preferredMode);
  }
}

function bindActions() {
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-camera-open]");
    if (!button) {
      return;
    }

    openCameraFromButton(button);
  });
}

function connectSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/live`);
  state.socket = socket;

  socket.addEventListener("open", () => {
    socket.send("ready");
  });

  socket.addEventListener("message", () => {
    loadOverview().catch(() => {});
  });

  socket.addEventListener("close", () => {
    window.setTimeout(connectSocket, 3000);
  });
}

window.addEventListener("DOMContentLoaded", async () => {
  bindActions();
  await loadOverview();
  connectSocket();
  window.setInterval(() => {
    loadOverview().catch(() => {});
  }, 8000);
});
