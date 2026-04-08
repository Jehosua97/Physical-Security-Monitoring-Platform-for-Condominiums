(function bootstrapCameraExperience() {
  const modalState = {
    root: null,
    currentCamera: null,
    mode: "webrtc",
    selectedClipUrl: null,
    playbackRequestId: 0,
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function buildSnapshotFallback(camera, label = "Sin video en vivo disponible") {
    if (camera?.snapshot_url) {
      return `
        <div class="camera-fallback-shell">
          <img class="camera-fallback-image" src="${camera.snapshot_url}" alt="Snapshot de ${escapeHtml(camera.name)}" />
          <div class="camera-fallback-copy">${escapeHtml(label)}</div>
        </div>
      `;
    }

    return `
      <div class="camera-fallback-shell camera-fallback-shell-empty">
        <div class="camera-fallback-copy">${escapeHtml(label)}</div>
      </div>
    `;
  }

  function buildEmbeddedPlayer(url, title, compact = false) {
    if (!url) {
      return "";
    }

    return `
      <div class="live-player-shell${compact ? " live-player-shell-compact" : ""}">
        <iframe
          class="live-player-frame"
          src="${url}"
          title="${escapeHtml(title)}"
          loading="lazy"
          allow="autoplay; fullscreen; picture-in-picture"
          allowfullscreen
          referrerpolicy="no-referrer"
        ></iframe>
      </div>
    `;
  }

  function buildCameraViewport(camera, options = {}) {
    const compact = Boolean(options.compact);
    const mode = options.mode || "webrtc";
    const media = camera?.media || {};
    const url = mode === "hls" ? media.hls_embed_url : media.webrtc_url;

    if (!camera || camera.status !== "online" || !url) {
      return buildSnapshotFallback(camera, "Camara fuera de linea o sin stream activo");
    }

    const title = `${camera.name} ${mode === "hls" ? "LL-HLS" : "WebRTC"}`;
    return buildEmbeddedPlayer(url, title, compact);
  }

  function ensureModal() {
    if (modalState.root) {
      return modalState.root;
    }

    const root = document.createElement("div");
    root.className = "camera-modal";
    root.innerHTML = `
      <div class="camera-modal-backdrop" data-camera-modal-close></div>
      <div class="camera-modal-dialog" role="dialog" aria-modal="true" aria-label="Camara ampliada">
        <div class="camera-modal-header">
          <div>
            <p class="section-label">Camara seleccionada</p>
            <h2 id="camera-modal-title">Camara</h2>
            <p class="camera-modal-meta" id="camera-modal-meta"></p>
          </div>
          <div class="camera-modal-toolbar">
            <button class="camera-modal-tab" type="button" data-camera-modal-mode="webrtc">En vivo</button>
            <button class="camera-modal-tab" type="button" data-camera-modal-mode="hls">LL-HLS</button>
            <button class="camera-modal-tab" type="button" data-camera-modal-mode="playback">Playback</button>
            <button class="camera-modal-icon" type="button" data-camera-modal-fullscreen>Pantalla completa</button>
            <button class="camera-modal-icon" type="button" data-camera-modal-close>Cerrar</button>
          </div>
        </div>
        <div class="camera-modal-body">
          <div class="camera-modal-stage" id="camera-modal-stage"></div>
          <aside class="camera-modal-sidebar" id="camera-modal-sidebar"></aside>
        </div>
      </div>
    `;

    root.addEventListener("click", (event) => {
      const closeTrigger = event.target.closest("[data-camera-modal-close]");
      if (closeTrigger) {
        closeCamera();
        return;
      }

      const modeTrigger = event.target.closest("[data-camera-modal-mode]");
      if (modeTrigger) {
        modalState.mode = modeTrigger.dataset.cameraModalMode;
        renderModal();
        return;
      }

      const clipTrigger = event.target.closest("[data-playback-url]");
      if (clipTrigger) {
        modalState.selectedClipUrl = clipTrigger.dataset.playbackUrl;
        updateSelectedPlaybackClip();
        return;
      }

      const fullscreenTrigger = event.target.closest("[data-camera-modal-fullscreen]");
      if (fullscreenTrigger) {
        requestModalFullscreen();
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeCamera();
      }
    });

    document.body.appendChild(root);
    modalState.root = root;
    return root;
  }

  function closeCamera() {
    if (!modalState.root) {
      return;
    }

    modalState.root.classList.remove("is-open");
  }

  function renderSidebar(camera) {
    const sidebar = document.getElementById("camera-modal-sidebar");
    if (!sidebar || !camera) {
      return;
    }

    const media = camera.media || {};
    sidebar.innerHTML = `
      <div class="camera-modal-sidebar-card">
        <p class="section-label">Contexto operativo</p>
        <div class="feed-badge-row">
          <span class="metric-chip">${escapeHtml(camera.site_id)}</span>
          <span class="metric-chip">${escapeHtml(camera.camera_id)}</span>
          <span class="metric-chip">${escapeHtml(camera.status || "sin estado")}</span>
        </div>
        <p class="camera-note">${escapeHtml(media.notes || "Sin detalle adicional de media.")}</p>
      </div>
      <div class="camera-modal-sidebar-card">
        <p class="section-label">Ruta RTSP del edge</p>
        <p class="camera-stream-value">${escapeHtml(media.ingest_rtsp_url || "No configurada")}</p>
      </div>
      <div class="camera-modal-sidebar-card">
        <p class="section-label">Ultimo snapshot</p>
        ${buildSnapshotFallback(camera, "Referencia visual del ultimo snapshot")}
      </div>
    `;
  }

  function setModalHeader(camera) {
    const title = document.getElementById("camera-modal-title");
    const meta = document.getElementById("camera-modal-meta");
    if (!title || !meta || !camera) {
      return;
    }

    title.textContent = camera.name;
    meta.textContent = `${camera.site_id} · ${camera.camera_id}`;
  }

  function setActiveTab() {
    document.querySelectorAll("[data-camera-modal-mode]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.cameraModalMode === modalState.mode);
    });
  }

  function renderLiveStage(camera, mode) {
    const stage = document.getElementById("camera-modal-stage");
    if (!stage) {
      return;
    }

    stage.innerHTML = `
      <div class="camera-modal-media" data-camera-modal-media>
        ${buildCameraViewport(camera, { mode })}
      </div>
    `;
  }

  function normalizePlaybackUrl(url) {
    if (!url) {
      return null;
    }

    return url.includes("format=") ? url : `${url}&format=mp4`;
  }

  function formatClipTime(value) {
    if (!value) {
      return "Sin fecha";
    }

    return new Intl.DateTimeFormat("es-CO", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(value));
  }

  function formatClipDuration(clip) {
    if (typeof clip.duration === "string" && clip.duration.trim()) {
      return clip.duration;
    }

    if (typeof clip.duration === "number" && Number.isFinite(clip.duration)) {
      return `${Math.round(clip.duration)} s`;
    }

    return "duracion no reportada";
  }

  function updateSelectedPlaybackClip() {
    if (!modalState.root || modalState.mode !== "playback") {
      return;
    }

    const video = modalState.root.querySelector("#camera-playback-video");
    if (video && modalState.selectedClipUrl) {
      video.src = modalState.selectedClipUrl;
      video.load();
    }

    modalState.root.querySelectorAll("[data-playback-url]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.playbackUrl === modalState.selectedClipUrl);
    });
  }

  async function renderPlaybackStage(camera) {
    const stage = document.getElementById("camera-modal-stage");
    if (!stage) {
      return;
    }

    const requestId = modalState.playbackRequestId + 1;
    modalState.playbackRequestId = requestId;

    stage.innerHTML = `
      <div class="camera-playback-panel">
        <div class="camera-playback-player">
          <div class="empty-state">Buscando segmentos grabados para esta camara...</div>
        </div>
        <div class="camera-playback-list" id="camera-playback-list"></div>
      </div>
    `;

    try {
      if (!camera?.media?.playback_list_url) {
        throw new Error("Esta camara no tiene playback configurado");
      }

      const listUrl = new URL(camera.media.playback_list_url);
      const end = new Date();
      const start = new Date(end.getTime() - 60 * 60 * 1000);
      listUrl.searchParams.set("start", start.toISOString());
      listUrl.searchParams.set("end", end.toISOString());

      const response = await fetch(listUrl.toString(), { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`Playback HTTP ${response.status}`);
      }

      const clips = await response.json();
      if (requestId !== modalState.playbackRequestId || modalState.currentCamera?.camera_id !== camera.camera_id) {
        return;
      }

      if (!Array.isArray(clips) || !clips.length) {
        stage.innerHTML = `
          <div class="camera-playback-panel">
            <div class="empty-state">
              Todavia no hay segmentos cerrados para esta camara. Espera unos segundos para que MediaMTX rote la
              siguiente grabacion.
            </div>
          </div>
        `;
        return;
      }

      const orderedClips = clips
        .map((clip) => ({
          ...clip,
          playbackUrl: normalizePlaybackUrl(clip.url),
        }))
        .filter((clip) => clip.playbackUrl)
        .sort((left, right) => new Date(right.start).getTime() - new Date(left.start).getTime());

      modalState.selectedClipUrl = orderedClips[0]?.playbackUrl || null;

      stage.innerHTML = `
        <div class="camera-playback-panel">
          <div class="camera-playback-player" data-camera-modal-media>
            <video id="camera-playback-video" controls playsinline></video>
          </div>
          <div class="camera-playback-list">
            ${orderedClips
              .map(
                (clip) => `
                  <button class="camera-playback-item" type="button" data-playback-url="${clip.playbackUrl}">
                    <strong>${escapeHtml(formatClipTime(clip.start))}</strong>
                    <span>${escapeHtml(formatClipDuration(clip))}</span>
                  </button>
                `
              )
              .join("")}
          </div>
        </div>
      `;

      updateSelectedPlaybackClip();
    } catch (error) {
      stage.innerHTML = `
        <div class="camera-playback-panel">
          <div class="empty-state">
            No fue posible consultar el playback historico. ${escapeHtml(error.message || "Error desconocido")}
          </div>
        </div>
      `;
    }
  }

  function renderModal() {
    const camera = modalState.currentCamera;
    if (!camera) {
      return;
    }

    ensureModal();
    setModalHeader(camera);
    setActiveTab();
    renderSidebar(camera);

    if (modalState.mode === "playback") {
      renderPlaybackStage(camera);
      return;
    }

    renderLiveStage(camera, modalState.mode);
  }

  function openCamera(camera, preferredMode = "webrtc") {
    if (!camera) {
      return;
    }

    ensureModal();
    modalState.currentCamera = camera;
    modalState.mode = preferredMode;
    modalState.selectedClipUrl = null;
    modalState.root.classList.add("is-open");
    renderModal();
  }

  function requestModalFullscreen() {
    const mediaTarget =
      modalState.root?.querySelector(".camera-modal-stage iframe, .camera-modal-stage video, .camera-modal-stage .camera-modal-media");
    if (mediaTarget && typeof mediaTarget.requestFullscreen === "function") {
      mediaTarget.requestFullscreen().catch(() => {});
    }
  }

  window.CameraExperience = {
    escapeHtml,
    buildCameraViewport,
    openCamera,
    closeCamera,
  };
})();
