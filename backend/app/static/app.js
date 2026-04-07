const state = {
  socket: null,
};

const STATUS_LABELS = {
  online: "En línea",
  offline: "Fuera de línea",
  approved: "Aprobado",
  pending: "Pendiente",
  denied: "Denegado",
  open: "Abierta",
  acknowledged: "Reconocida",
  closed: "Cerrada",
  low: "Baja",
  medium: "Media",
  high: "Alta",
  critical: "Crítica",
};

function formatTime(value) {
  if (!value) {
    return "Sin datos aún";
  }

  const date = new Date(value);
  return new Intl.DateTimeFormat("es-CO", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function translateStatus(value) {
  return STATUS_LABELS[value] || value || "Sin estado";
}

function renderKpis(kpis) {
  const items = [
    ["Sitios en línea", `${kpis.sites_online}/${kpis.sites_total}`],
    ["Cámaras en línea", `${kpis.cameras_online}`],
    ["Eventos de visitantes", `${kpis.visitors_total}`],
    ["Alertas abiertas", `${kpis.alerts_open}`],
    ["Operación remota", "3 condominios simulados"],
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

function statusClass(status) {
  return `status-pill status-${(status || "unknown").toLowerCase()}`;
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
              <span class="metric-chip">${site.active_cameras} cámaras activas</span>
              <span class="metric-chip">${site.recent_visitors} visitantes recientes</span>
              <span class="metric-chip">${site.recent_alerts} alertas abiertas</span>
              <span class="metric-chip">Última señal ${formatTime(site.last_seen)}</span>
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
      alerts: "Sin alertas todavía. Los simuladores siguen calentando.",
      visitors: "Sin visitantes todavía. Los simuladores siguen calentando.",
    };
    container.innerHTML = `<div class="empty-state">${messages[kind] || "Sin datos aún."}</div>`;
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

function renderCameras(cameras) {
  const container = document.getElementById("camera-grid");
  if (!cameras.length) {
    container.innerHTML =
      '<div class="empty-state">Las cámaras simuladas todavía están enviando sus primeros snapshots.</div>';
    return;
  }

  container.innerHTML = cameras
    .map(
      (camera) => `
        <article class="camera-card">
          ${
            camera.snapshot_url
              ? `<img src="${camera.snapshot_url}" alt="Snapshot de ${camera.name}" />`
              : '<div class="site-preview"></div>'
          }
          <div class="camera-body">
            <div class="site-topline">
              <div>
                <h3>${camera.name}</h3>
                <p class="site-address">${camera.site_id}</p>
              </div>
              <span class="${statusClass(camera.status)}">${translateStatus(camera.status)}</span>
            </div>
            <p class="site-address">${camera.stream_url || "Placeholder de streaming para fase futura"}</p>
            <p class="camera-note">La etapa 1 usa snapshots actualizados, no video reproducible en navegador todavía.</p>
          </div>
        </article>
      `
    )
    .join("");
}

async function loadOverview() {
  const response = await fetch("/dashboard/overview", { cache: "no-store" });
  const data = await response.json();
  renderKpis(data.kpis);
  renderSites(data.sites);
  renderFeed("alerts-list", data.latest_alerts, "alerts");
  renderFeed("visitors-list", data.latest_visitors, "visitors");
  renderCameras(data.latest_cameras);
  document.getElementById("generated-at").textContent = `Vista actualizada ${formatTime(data.generated_at)}`;
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
  await loadOverview();
  connectSocket();
  window.setInterval(() => {
    loadOverview().catch(() => {});
  }, 8000);
});
