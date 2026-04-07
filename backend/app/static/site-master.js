const masterState = {
  siteId: window.SITE_MASTER_CONFIG.siteId,
  socket: null,
  requestInFlight: false,
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
  in_progress: "En ejecución",
  completed: "Completada",
  failed: "Fallida",
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

function statusClass(status) {
  return `status-pill status-${(status || "unknown").toLowerCase()}`;
}

function setOperatorStatus(message, tone = "neutral") {
  const element = document.getElementById("operator-status");
  element.textContent = message;
  element.dataset.tone = tone;
}

function setActionButtonsDisabled(disabled) {
  document.querySelectorAll(".action-button").forEach((button) => {
    button.disabled = disabled;
  });
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || `Falló la operación ${response.status}`);
  }

  return response.json();
}

function renderMasterKpis(site, kpis) {
  const items = [
    ["Estado del sitio", translateStatus(site.status)],
    ["Cámaras activas", `${kpis.active_cameras}/${kpis.total_cameras}`],
    ["Alertas abiertas", `${kpis.open_alerts}`],
    ["Visitantes recientes", `${kpis.recent_visitors}`],
    ["Acciones pendientes", `${kpis.acciones_pendientes}`],
  ];

  document.getElementById("master-kpi-grid").innerHTML = items
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

function renderMasterCameras(cameras) {
  const container = document.getElementById("master-camera-wall");
  if (!cameras.length) {
    container.innerHTML = '<div class="empty-state">Aún no reportan cámaras para este condominio.</div>';
    return;
  }

  container.innerHTML = cameras
    .map(
      (camera) => `
        <article class="camera-frame">
          ${
            camera.snapshot_url
              ? `<img class="camera-frame-image" src="${camera.snapshot_url}" alt="Snapshot de ${camera.name}" />`
              : '<div class="camera-frame-image camera-frame-placeholder"></div>'
          }
          <div class="camera-frame-body">
            <div class="site-topline">
              <div>
                <h3>${camera.name}</h3>
                <p class="site-address">${camera.camera_id}</p>
              </div>
              <span class="${statusClass(camera.status)}">${translateStatus(camera.status)}</span>
            </div>
            <p class="feed-meta">Última actualización ${formatTime(camera.last_seen)}</p>
            <div class="camera-stream-box">
              <p class="camera-stream-label">Endpoint futuro de streaming</p>
              <p class="camera-stream-value">${camera.stream_url || "No configurado"}</p>
            </div>
          </div>
        </article>
      `
    )
    .join("");
}

function renderAlerts(alerts) {
  const container = document.getElementById("master-alerts-list");
  if (!alerts.length) {
    container.innerHTML = '<div class="empty-state">Sin alertas para este sitio por ahora.</div>';
    return;
  }

  container.innerHTML = alerts
    .map(
      (alert) => `
        <article class="feed-card">
          <div class="feed-topline">
            <p class="feed-title">${alert.message}</p>
            <span class="${statusClass(alert.severity)}">${translateStatus(alert.severity)}</span>
          </div>
          <p class="feed-meta">${alert.source_type} ${alert.source_id}</p>
          <div class="feed-badge-row">
            <span class="metric-chip">${translateStatus(alert.status)}</span>
            <span class="metric-chip">${formatTime(alert.timestamp)}</span>
          </div>
        </article>
      `
    )
    .join("");
}

function renderRecentVisitors(visitors) {
  const container = document.getElementById("master-visitors-list");
  if (!visitors.length) {
    container.innerHTML = '<div class="empty-state">Todavía no hay actividad de visitantes para este sitio.</div>';
    return;
  }

  container.innerHTML = visitors
    .map(
      (visitor) => `
        <article class="feed-card">
          <div class="feed-image-row">
            ${
              visitor.snapshot_url
                ? `<img class="feed-thumb" src="${visitor.snapshot_url}" alt="Registro de ${visitor.visitor_name}" />`
                : ""
            }
            <div class="feed-image-body">
              <div class="feed-topline">
                <p class="feed-title">${visitor.visitor_name}</p>
                <span class="${statusClass(visitor.status)}">${translateStatus(visitor.status)}</span>
              </div>
              <p class="feed-meta">Unidad ${visitor.unit_to_visit} · Residente ${visitor.host_name}</p>
              <div class="feed-badge-row">
                <span class="metric-chip">${visitor.id_type}</span>
                <span class="metric-chip">${formatTime(visitor.timestamp)}</span>
              </div>
              ${
                visitor.notes
                  ? `<p class="feed-note">${visitor.notes}</p>`
                  : ""
              }
            </div>
          </div>
        </article>
      `
    )
    .join("");
}

function renderPendingVisitors(visitors) {
  const container = document.getElementById("pending-visitors-list");
  if (!visitors.length) {
    container.innerHTML =
      '<div class="empty-state">No hay solicitudes pendientes. Las nuevas revisiones aparecerán aquí.</div>';
    return;
  }

  container.innerHTML = visitors
    .map(
      (visitor) => `
        <article class="feed-card">
          <div class="feed-image-row">
            ${
              visitor.snapshot_url
                ? `<img class="feed-thumb" src="${visitor.snapshot_url}" alt="Registro pendiente de ${visitor.visitor_name}" />`
                : ""
            }
            <div class="feed-image-body">
              <div class="feed-topline">
                <p class="feed-title">${visitor.visitor_name}</p>
                <span class="${statusClass(visitor.status)}">${translateStatus(visitor.status)}</span>
              </div>
              <p class="feed-meta">Unidad ${visitor.unit_to_visit} · Residente ${visitor.host_name}</p>
              <div class="feed-badge-row">
                <span class="metric-chip">${visitor.id_type}</span>
                <span class="metric-chip">${formatTime(visitor.timestamp)}</span>
              </div>
            </div>
          </div>
          <div class="visitor-approval-actions">
            <button
              class="action-button"
              type="button"
              data-visitor-decision="approve-open"
              data-event-id="${visitor.event_id}"
              data-visitor-name="${visitor.visitor_name}"
            >
              Aprobar y abrir puerta
            </button>
            <button
              class="action-button action-button-secondary"
              type="button"
              data-visitor-decision="approve"
              data-event-id="${visitor.event_id}"
              data-visitor-name="${visitor.visitor_name}"
            >
              Solo aprobar
            </button>
            <button
              class="action-button action-button-danger"
              type="button"
              data-visitor-decision="deny"
              data-event-id="${visitor.event_id}"
              data-visitor-name="${visitor.visitor_name}"
            >
              Denegar acceso
            </button>
          </div>
        </article>
      `
    )
    .join("");
}

function renderRecentActions(actions) {
  const container = document.getElementById("master-actions-list");
  if (!actions.length) {
    container.innerHTML = '<div class="empty-state">Todavía no se han ejecutado acciones remotas en este sitio.</div>';
    return;
  }

  container.innerHTML = actions
    .map(
      (action) => `
        <article class="feed-card">
          <div class="feed-topline">
            <p class="feed-title">${action.command}</p>
            <span class="${statusClass(action.status)}">${translateStatus(action.status)}</span>
          </div>
          <p class="feed-meta">${action.target_id} · solicitado por ${action.requested_by}</p>
          <div class="feed-badge-row">
            <span class="metric-chip">${action.action_type}</span>
            <span class="metric-chip">${formatTime(action.completed_at || action.started_at || action.created_at)}</span>
          </div>
          <p class="feed-note">${action.result_message || "Esperando ejecución por el edge-agent del condominio."}</p>
        </article>
      `
    )
    .join("");
}

async function loadMasterView() {
  const response = await fetch(`/dashboard/sites/${masterState.siteId}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`No fue posible cargar la vista maestra de ${masterState.siteId}`);
  }

  const data = await response.json();
  document.getElementById("master-title").textContent = data.site.name;
  document.getElementById(
    "master-copy"
  ).textContent = `${data.site.address}. Desde esta pantalla el operador central ve snapshots, decide aprobaciones y envía acciones remotas al condominio.`;
  document.getElementById("master-generated-at").textContent = `Actualizado ${formatTime(data.generated_at)}`;
  document.getElementById("live-mode-note").innerHTML = `
    <strong>${data.live_mode.title}.</strong>
    ${data.live_mode.description}
  `;

  renderMasterKpis(data.site, data.kpis);
  renderMasterCameras(data.cameras);
  renderAlerts(data.latest_alerts);
  renderRecentVisitors(data.latest_visitors);
  renderPendingVisitors(data.pending_visitors);
  renderRecentActions(data.recent_actions);
}

async function triggerManualAction(commandConfig) {
  if (masterState.requestInFlight) {
    return;
  }

  masterState.requestInFlight = true;
  setActionButtonsDisabled(true);
  setOperatorStatus(commandConfig.loadingMessage, "neutral");

  try {
    const action = await postJson(`/sites/${masterState.siteId}/actions`, {
      action_type: commandConfig.actionType,
      target_id: commandConfig.targetId,
      command: commandConfig.command,
      requested_by: "Centro de monitoreo",
      payload: commandConfig.payload,
    });
    setOperatorStatus(
      `Comando enviado. Acción ${action.action_id} en estado ${translateStatus(action.status)}.`,
      "success"
    );
    await loadMasterView();
  } catch (error) {
    setOperatorStatus(`No se pudo enviar el comando remoto: ${error.message}`, "error");
  } finally {
    masterState.requestInFlight = false;
    setActionButtonsDisabled(false);
  }
}

async function handleVisitorDecision(button) {
  if (masterState.requestInFlight) {
    return;
  }

  const decisionType = button.dataset.visitorDecision;
  const eventId = button.dataset.eventId;
  const visitorName = button.dataset.visitorName;
  const isApproveWithDoor = decisionType === "approve-open";
  const decision = decisionType === "deny" ? "denied" : "approved";

  masterState.requestInFlight = true;
  setActionButtonsDisabled(true);
  setOperatorStatus(`Procesando decisión para ${visitorName}...`, "neutral");

  try {
    const result = await postJson(`/visitors/events/${eventId}/decision`, {
      decision,
      operator_name: "Centro de monitoreo",
      trigger_remote_action: isApproveWithDoor,
    });

    const baseMessage =
      decision === "approved"
        ? `Visita aprobada para ${visitorName}.`
        : `Acceso denegado para ${visitorName}.`;
    const actionMessage = result.remote_action
      ? ` Acción remota ${result.remote_action.command} enviada al sitio.`
      : "";

    setOperatorStatus(`${baseMessage}${actionMessage}`, "success");
    await loadMasterView();
  } catch (error) {
    setOperatorStatus(`No se pudo registrar la decisión: ${error.message}`, "error");
  } finally {
    masterState.requestInFlight = false;
    setActionButtonsDisabled(false);
  }
}

function bindStaticActions() {
  document.getElementById("open-door-button").addEventListener("click", () => {
    triggerManualAction({
      actionType: "door_control",
      targetId: `${masterState.siteId}-main-gate`,
      command: "open_door",
      payload: {
        motivo: "Apertura manual desde la vista maestra",
      },
      loadingMessage: "Encolando apertura remota de puerta principal...",
    });
  });

  document.getElementById("toggle-light-button").addEventListener("click", () => {
    triggerManualAction({
      actionType: "lighting",
      targetId: `${masterState.siteId}-lobby-light`,
      command: "toggle_lobby_light",
      payload: {
        motivo: "Encendido manual desde la vista maestra",
      },
      loadingMessage: "Encolando activación remota de la luz del lobby...",
    });
  });

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-visitor-decision]");
    if (!button) {
      return;
    }
    handleVisitorDecision(button);
  });
}

function connectSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/live`);
  masterState.socket = socket;

  socket.addEventListener("open", () => {
    socket.send("ready");
  });

  socket.addEventListener("message", () => {
    loadMasterView().catch(() => {});
  });

  socket.addEventListener("close", () => {
    window.setTimeout(connectSocket, 3000);
  });
}

window.addEventListener("DOMContentLoaded", async () => {
  bindStaticActions();
  await loadMasterView();
  connectSocket();
  window.setInterval(() => {
    loadMasterView().catch(() => {});
  }, 8000);
});
