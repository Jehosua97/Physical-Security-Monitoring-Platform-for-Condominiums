import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests


@dataclass
class TbDeviceRef:
    device_id: str
    name: str
    token: str


class ThingsBoardBridge:
    def __init__(self) -> None:
        self.enabled = os.getenv("THINGSBOARD_ENABLED", "true").lower() == "true"
        self.base_url = os.getenv("THINGSBOARD_URL", "http://thingsboard:9090").rstrip("/")
        self.tenant_username = os.getenv("THINGSBOARD_TENANT_USERNAME", "tenant@thingsboard.org")
        self.tenant_password = os.getenv("THINGSBOARD_TENANT_PASSWORD", "tenant")
        self.dashboard_title = os.getenv(
            "THINGSBOARD_DASHBOARD_TITLE",
            "Condominium Security Operations",
        )
        self.session = requests.Session()
        self.lock = threading.Lock()
        self._tenant_token: str | None = None
        self._device_cache: dict[str, TbDeviceRef] = {}
        self._dashboard_id: str | None = None
        self._ready = False
        self._last_error: str | None = None

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "ready": self._ready,
            "base_url": self.base_url,
            "dashboard_title": self.dashboard_title,
            "dashboard_id": self._dashboard_id,
            "last_error": self._last_error,
        }

    def bootstrap(self) -> bool:
        if not self.enabled:
            return False

        with self.lock:
            if self._ready and self._tenant_token and self._dashboard_id is not None:
                return True
            try:
                self._login()
                self._ready = True
                self._last_error = None
                try:
                    self._ensure_dashboard()
                except Exception as exc:
                    self._last_error = f"dashboard seed failed: {exc}"
                    print(f"thingsboard dashboard seed failed: {exc}")
                return True
            except Exception as exc:
                self._ready = False
                self._last_error = str(exc)
                print(f"thingsboard bootstrap failed: {exc}")
                return False

    def publish_summary(self, kpis: dict[str, Any]) -> None:
        if not self.bootstrap():
            return

        device = self._ensure_device(
            name="security-ops-central",
            device_type="security_ops_summary",
            label="Central Operations Summary",
        )
        self._post_attributes(
            device.token,
            {
                "entity_class": "summary",
                "prototype_stage": "stage-1",
                "integration": "backend-sync",
            },
        )
        self._post_telemetry(
            device.token,
            {
                "sites_online": int(kpis.get("sites_online", 0)),
                "sites_total": int(kpis.get("sites_total", 0)),
                "cameras_online": int(kpis.get("cameras_online", 0)),
                "visitors_total": int(kpis.get("visitors_total", 0)),
                "alerts_open": int(kpis.get("alerts_open", 0)),
                "last_sync": datetime.utcnow().isoformat() + "Z",
            },
        )

    def publish_site(self, snapshot: dict[str, Any]) -> None:
        if not self.bootstrap():
            return

        site_id = snapshot["site_id"]
        device = self._ensure_device(
            name=f"site-{site_id}",
            device_type="condo_site",
            label=snapshot["site_name"],
        )
        self._post_attributes(
            device.token,
            {
                "entity_class": "site",
                "site_id": site_id,
                "site_name": snapshot["site_name"],
                "address": snapshot["address"],
            },
        )
        self._post_telemetry(
            device.token,
            {
                "status": snapshot["status"],
                "is_online": 1 if snapshot["status"] == "online" else 0,
                "active_cameras": int(snapshot["active_cameras"]),
                "open_alerts": int(snapshot["open_alerts"]),
                "last_seen": snapshot["last_seen"],
                "last_seen_epoch": int(snapshot["last_seen_epoch"]),
                "latest_visitor_name": snapshot["latest_visitor_name"],
                "latest_visitor_status": snapshot["latest_visitor_status"],
                "latest_visitor_unit": snapshot["latest_visitor_unit"],
                "latest_alert_message": snapshot["latest_alert_message"],
                "latest_alert_severity": snapshot["latest_alert_severity"],
            },
        )

    def publish_camera(self, snapshot: dict[str, Any]) -> None:
        if not self.bootstrap():
            return

        device = self._ensure_device(
            name=f"camera-{snapshot['camera_id']}",
            device_type="condo_camera",
            label=snapshot["camera_name"],
        )
        self._post_attributes(
            device.token,
            {
                "entity_class": "camera",
                "site_id": snapshot["site_id"],
                "site_name": snapshot["site_name"],
                "camera_id": snapshot["camera_id"],
                "camera_name": snapshot["camera_name"],
            },
        )
        self._post_telemetry(
            device.token,
            {
                "status": snapshot["status"],
                "is_online": 1 if snapshot["status"] == "online" else 0,
                "snapshot_url": snapshot["snapshot_url"] or "",
                "stream_url": snapshot["stream_url"] or "",
                "last_seen": snapshot["last_seen"],
                "last_seen_epoch": int(snapshot["last_seen_epoch"]),
            },
        )

    def _login(self, force: bool = False) -> None:
        if self._tenant_token and not force:
            return

        response = self.session.post(
            f"{self.base_url}/api/auth/login",
            json={"username": self.tenant_username, "password": self.tenant_password},
            timeout=15,
        )
        response.raise_for_status()
        self._tenant_token = response.json()["token"]

    def _api(self, method: str, path: str, retry: bool = True, **kwargs):
        self._login()
        headers = kwargs.pop("headers", {})
        headers["X-Authorization"] = f"Bearer {self._tenant_token}"
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            headers=headers,
            timeout=20,
            **kwargs,
        )
        if response.status_code == 401 and retry:
            self._login(force=True)
            return self._api(method, path, retry=False, headers=headers, **kwargs)
        response.raise_for_status()
        if response.content:
            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                return response.json()
        return None

    def _ensure_device(self, *, name: str, device_type: str, label: str) -> TbDeviceRef:
        cached = self._device_cache.get(name)
        if cached is not None:
            return cached

        found = self._find_device_by_name(name)
        if found is None:
            token = self._device_token(name)
            payload = {
                "device": {
                    "name": name,
                    "type": device_type,
                    "label": label,
                },
                "credentials": {
                    "credentialsType": "ACCESS_TOKEN",
                    "credentialsId": token,
                },
            }
            created = self._api("POST", "/api/device-with-credentials", json=payload)
            device_id = created["id"]["id"]
        else:
            device_id = found["id"]["id"]
            credentials = self._api("GET", f"/api/device/{device_id}/credentials")
            token = credentials["credentialsId"]

        ref = TbDeviceRef(device_id=device_id, name=name, token=token)
        self._device_cache[name] = ref
        return ref

    def _find_device_by_name(self, name: str) -> dict[str, Any] | None:
        page = self._api(
            "GET",
            f"/api/tenant/deviceInfos?pageSize=20&page=0&textSearch={name}&sortProperty=name&sortOrder=ASC",
        )
        for item in page.get("data", []):
            if item.get("name") == name:
                return item
        return None

    def _ensure_dashboard(self) -> None:
        existing = self._find_dashboard_by_title(self.dashboard_title)
        payload = {
            "title": self.dashboard_title,
            "name": self.dashboard_title,
            "mobileHide": False,
            "configuration": self._dashboard_config(),
        }
        if existing is not None:
            payload["id"] = existing["id"]
            payload["tenantId"] = existing["tenantId"]

        saved = self._api("POST", "/api/dashboard", json=payload)
        if saved and saved.get("id"):
            self._dashboard_id = saved["id"]["id"]

    def _find_dashboard_by_title(self, title: str) -> dict[str, Any] | None:
        page = self._api(
            "GET",
            f"/api/tenant/dashboards?pageSize=20&page=0&textSearch={title}&sortProperty=title&sortOrder=ASC",
        )
        for item in page.get("data", []):
            if item.get("title") == title:
                return item
        return None

    def _post_telemetry(self, device_token: str, payload: dict[str, Any]) -> None:
        response = self.session.post(
            f"{self.base_url}/api/v1/{device_token}/telemetry",
            json=payload,
            timeout=15,
        )
        response.raise_for_status()

    def _post_attributes(self, device_token: str, payload: dict[str, Any]) -> None:
        response = self.session.post(
            f"{self.base_url}/api/v1/{device_token}/attributes",
            json=payload,
            timeout=15,
        )
        response.raise_for_status()

    def _device_token(self, name: str) -> str:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"psmp-thingsboard::{name}").hex

    def _dashboard_config(self) -> dict[str, Any]:
        summary_alias = "summary_alias"
        site_alias = "site_alias"
        camera_alias = "camera_alias"
        summary_widget = "summary_widget"
        sites_widget = "sites_widget"
        cameras_widget = "cameras_widget"
        return {
            "widgets": {
                summary_widget: self._table_widget(
                    widget_id=summary_widget,
                    alias_id=summary_alias,
                    title="Resumen central de KPIs",
                    entity_title="Resumen operativo",
                    entity_name_title="Dispositivo resumen",
                    data_keys=[
                        self._telemetry_key("sites_online", "Sitios en linea"),
                        self._telemetry_key("sites_total", "Sitios totales"),
                        self._telemetry_key("cameras_online", "Camaras en linea"),
                        self._telemetry_key("alerts_open", "Alertas abiertas"),
                        self._telemetry_key("visitors_total", "Eventos de visitantes"),
                    ],
                ),
                sites_widget: self._table_widget(
                    widget_id=sites_widget,
                    alias_id=site_alias,
                    title="Sitios de condominios",
                    entity_title="Condominios",
                    entity_name_title="Sitio",
                    data_keys=[
                        self._status_key("status", "Estado"),
                        self._telemetry_key("active_cameras", "Camaras activas"),
                        self._telemetry_key("open_alerts", "Alertas abiertas"),
                        self._telemetry_key("latest_visitor_name", "Ultimo visitante"),
                        self._status_key("latest_visitor_status", "Estado del visitante"),
                        self._status_key("latest_alert_severity", "Severidad alerta"),
                        self._telemetry_key("latest_alert_message", "Ultima alerta"),
                    ],
                ),
                cameras_widget: self._table_widget(
                    widget_id=cameras_widget,
                    alias_id=camera_alias,
                    title="Flota de camaras",
                    entity_title="Camaras",
                    entity_name_title="Camara",
                    data_keys=[
                        self._attribute_key("site_name", "Sitio"),
                        self._status_key("status", "Estado"),
                        self._telemetry_key("stream_url", "URL de stream"),
                        self._telemetry_key("snapshot_url", "URL de snapshot"),
                        self._telemetry_key("last_seen", "Ultima actividad"),
                    ],
                ),
            },
            "entityAliases": {
                summary_alias: self._device_type_alias(summary_alias, "Resumen de seguridad", ["security_ops_summary"]),
                site_alias: self._device_type_alias(site_alias, "Sitios de condominios", ["condo_site"]),
                camera_alias: self._device_type_alias(camera_alias, "Camaras de condominios", ["condo_camera"]),
            },
            "states": {
                "default": {
                    "name": "Resumen operativo",
                    "root": True,
                    "layouts": {
                        "main": {
                            "widgets": {
                                summary_widget: {"sizeX": 24, "sizeY": 5, "row": 0, "col": 0},
                                sites_widget: {"sizeX": 24, "sizeY": 8, "row": 5, "col": 0},
                                cameras_widget: {"sizeX": 24, "sizeY": 10, "row": 13, "col": 0},
                            },
                            "gridSettings": {
                                "backgroundColor": "#eeeeee",
                                "color": "rgba(0,0,0,0.87)",
                                "columns": 24,
                                "backgroundSizeMode": "100%",
                                "autoFillHeight": True,
                                "mobileAutoFillHeight": False,
                                "mobileRowHeight": 70,
                                "margin": 10,
                                "outerMargin": True,
                                "layoutType": "default",
                            },
                        }
                    },
                }
            },
            "timewindow": {
                "displayValue": "",
                "selectedTab": 0,
                "hideAggregation": False,
                "hideAggInterval": False,
                "realtime": {"interval": 1000, "timewindowMs": 60000},
                "history": {
                    "historyType": 0,
                    "interval": 1000,
                    "timewindowMs": 60000,
                    "fixedTimewindow": {"startTimeMs": 0, "endTimeMs": 0},
                },
                "aggregation": {"type": "NONE", "limit": 200},
            },
            "settings": {
                "stateControllerId": "default",
                "showTitle": True,
                "showDashboardsSelect": True,
                "showEntitiesSelect": True,
                "showDashboardTimewindow": True,
                "showDashboardExport": True,
                "toolbarAlwaysOpen": False,
                "titleColor": "rgba(0,0,0,0.87)",
                "showDashboardLogo": False,
                "hideToolbar": False,
                "showFilters": True,
                "showUpdateDashboardImage": False,
                "dashboardCss": "",
            },
            "filters": {},
        }

    def _table_widget(
        self,
        *,
        widget_id: str,
        alias_id: str,
        title: str,
        entity_title: str,
        entity_name_title: str,
        data_keys: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "id": widget_id,
            "type": "latest",
            "typeFullFqn": "system.cards.entities_table",
            "sizeX": 24,
            "sizeY": 6,
            "config": {
                "timewindow": {
                    "displayValue": "",
                    "selectedTab": 0,
                    "realtime": {
                        "realtimeType": 1,
                        "interval": 1000,
                        "timewindowMs": 86400000,
                        "quickInterval": "CURRENT_DAY",
                        "hideInterval": False,
                        "hideLastInterval": False,
                        "hideQuickInterval": False,
                    },
                    "history": {
                        "historyType": 0,
                        "interval": 1000,
                        "timewindowMs": 60000,
                        "fixedTimewindow": {"startTimeMs": 0, "endTimeMs": 0},
                        "quickInterval": "CURRENT_DAY",
                        "hideInterval": False,
                        "hideLastInterval": False,
                        "hideFixedInterval": False,
                        "hideQuickInterval": False,
                    },
                    "aggregation": {"type": "NONE", "limit": 200},
                },
                "showTitle": True,
                "backgroundColor": "rgb(255, 255, 255)",
                "color": "rgba(0, 0, 0, 0.87)",
                "padding": "4px",
                "settings": {
                    "enableSearch": True,
                    "displayPagination": True,
                    "defaultPageSize": 10,
                    "defaultSortOrder": "entityName",
                    "displayEntityName": True,
                    "displayEntityType": False,
                    "enableSelectColumnDisplay": False,
                    "entitiesTitle": entity_title,
                    "displayEntityLabel": False,
                    "entityNameColumnTitle": entity_name_title,
                },
                "title": title,
                "dropShadow": True,
                "enableFullscreen": True,
                "titleStyle": {
                    "fontSize": "16px",
                    "fontWeight": 400,
                    "padding": "5px 10px 5px 10px",
                },
                "useDashboardTimewindow": False,
                "showLegend": False,
                "datasources": [
                    {
                        "type": "entity",
                        "name": None,
                        "entityAliasId": alias_id,
                        "dataKeys": data_keys,
                    }
                ],
                "showTitleIcon": False,
                "titleIcon": None,
                "iconColor": "rgba(0, 0, 0, 0.87)",
                "iconSize": "24px",
                "titleTooltip": "",
                "widgetStyle": {},
                "displayTimewindow": True,
                "actions": {"headerButton": [], "actionCellButton": [], "rowClick": []},
            },
        }

    def _device_type_alias(self, alias_id: str, alias: str, device_types: list[str]) -> dict[str, Any]:
        return {
            "id": alias_id,
            "alias": alias,
            "filter": {
                "type": "deviceType",
                "resolveMultiple": True,
                "deviceNameFilter": "",
                "deviceTypes": device_types,
            },
        }

    def _telemetry_key(self, name: str, label: str) -> dict[str, Any]:
        return {
            "name": name,
            "type": "timeseries",
            "label": label,
            "color": "#2196f3",
            "settings": {
                "columnWidth": "0px",
                "useCellStyleFunction": False,
                "useCellContentFunction": False,
            },
        }

    def _attribute_key(self, name: str, label: str) -> dict[str, Any]:
        return {
            "name": name,
            "type": "attribute",
            "label": label,
            "color": "#607d8b",
            "settings": {
                "columnWidth": "0px",
                "useCellStyleFunction": False,
                "useCellContentFunction": False,
            },
        }

    def _status_key(self, name: str, label: str) -> dict[str, Any]:
        style_function = (
            "var palette = {online:'rgb(39,134,34)',approved:'rgb(39,134,34)',"
            "pending:'rgb(233,137,0)',medium:'rgb(233,137,0)',"
            "high:'rgb(220,53,69)',critical:'rgb(220,53,69)',"
            "offline:'rgb(220,53,69)',denied:'rgb(220,53,69)'};"
            "var color = palette[(value || '').toString().toLowerCase()] || 'rgba(0,0,0,0.87)';"
            "return {color: color, fontWeight: '600'};"
        )
        content_function = (
            "var translations = {"
            "online:'En linea',offline:'Fuera de linea',approved:'Aprobado',"
            "pending:'Pendiente',denied:'Denegado',open:'Abierta',"
            "acknowledged:'Reconocida',closed:'Cerrada',low:'Baja',"
            "medium:'Media',high:'Alta',critical:'Critica'};"
            "var normalized = (value || '').toString().toLowerCase();"
            "return translations[normalized] || value;"
        )
        return {
            "name": name,
            "type": "timeseries",
            "label": label,
            "color": "#4caf50",
            "settings": {
                "columnWidth": "0px",
                "useCellStyleFunction": True,
                "useCellContentFunction": True,
                "cellStyleFunction": style_function,
                "cellContentFunction": content_function,
            },
        }


thingsboard_bridge = ThingsBoardBridge()
