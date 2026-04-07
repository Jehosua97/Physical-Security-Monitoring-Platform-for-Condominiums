import html
import io
import os
import textwrap
import uuid
from typing import Iterable

from minio import Minio
from minio.error import S3Error
from sqlalchemy.orm import Session

from .models import MediaAsset


class MediaStore:
    def __init__(self) -> None:
        endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")
        access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
        secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")
        secure = os.getenv("MINIO_SECURE", "false").lower() == "true"

        self.bucket = os.getenv("MINIO_BUCKET", "security-media")
        self.public_url = os.getenv("API_PUBLIC_URL", "http://localhost:8000").rstrip("/")
        self.client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def create_placeholder(
        self,
        db: Session,
        *,
        category: str,
        title: str,
        subtitle: str,
        footer_lines: Iterable[str],
        accent: str,
        site_id: str | None = None,
        camera_id: str | None = None,
        description: str | None = None,
    ) -> str:
        media_id = uuid.uuid4().hex
        object_name = f"{category}/{site_id or 'shared'}/{media_id}.svg"
        svg_bytes = self._build_svg(title, subtitle, footer_lines, accent)
        self._upload_bytes(object_name, svg_bytes, "image/svg+xml")
        asset = MediaAsset(
            id=media_id,
            object_name=object_name,
            content_type="image/svg+xml",
            category=category,
            site_id=site_id,
            camera_id=camera_id,
            description=description,
            size_bytes=len(svg_bytes),
        )
        db.add(asset)
        db.flush()
        return f"{self.public_url}/media/{media_id}"

    def upload_file(
        self,
        db: Session,
        *,
        content: bytes,
        filename: str,
        content_type: str,
        category: str,
        site_id: str | None = None,
        camera_id: str | None = None,
        description: str | None = None,
    ) -> str:
        extension = os.path.splitext(filename)[1] or ".bin"
        media_id = uuid.uuid4().hex
        object_name = f"{category}/{site_id or 'shared'}/{media_id}{extension}"
        self._upload_bytes(object_name, content, content_type)
        asset = MediaAsset(
            id=media_id,
            object_name=object_name,
            content_type=content_type,
            category=category,
            site_id=site_id,
            camera_id=camera_id,
            description=description,
            size_bytes=len(content),
        )
        db.add(asset)
        db.flush()
        return f"{self.public_url}/media/{media_id}"

    def fetch_asset(self, media_id: str, db: Session) -> tuple[MediaAsset, bytes]:
        asset = db.get(MediaAsset, media_id)
        if asset is None:
            raise KeyError(media_id)

        response = self.client.get_object(self.bucket, asset.object_name)
        try:
            content = response.read()
        finally:
            response.close()
            response.release_conn()
        return asset, content

    def _upload_bytes(self, object_name: str, content: bytes, content_type: str) -> None:
        try:
            self.client.put_object(
                self.bucket,
                object_name,
                io.BytesIO(content),
                len(content),
                content_type=content_type,
            )
        except S3Error as exc:
            raise RuntimeError(f"unable to upload media object {object_name}: {exc}") from exc

    def _build_svg(
        self,
        title: str,
        subtitle: str,
        footer_lines: Iterable[str],
        accent: str,
    ) -> bytes:
        safe_title = html.escape(title[:42])
        safe_subtitle = html.escape(subtitle[:64])
        safe_lines = [html.escape(line[:48]) for line in footer_lines]
        footer = "\n".join(
            f"<text x='52' y='{260 + (index * 24)}' class='meta'>{line}</text>"
            for index, line in enumerate(safe_lines[:3])
        )
        svg = f"""
        <svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
          <defs>
            <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#08121f" />
              <stop offset="65%" stop-color="#13253d" />
              <stop offset="100%" stop-color="#071118" />
            </linearGradient>
          </defs>
          <rect width="960" height="540" fill="url(#bg)" />
          <circle cx="130" cy="110" r="140" fill="{accent}" opacity="0.18" />
          <circle cx="820" cy="420" r="170" fill="{accent}" opacity="0.12" />
          <rect x="42" y="42" width="876" height="456" rx="28" fill="rgba(255,255,255,0.03)" stroke="rgba(255,255,255,0.12)" />
          <rect x="52" y="52" width="856" height="40" rx="20" fill="rgba(255,255,255,0.05)" />
          <text x="78" y="78" class="header">VISTA PREVIA OPERATIVA</text>
          <text x="52" y="180" class="title">{safe_title}</text>
          <text x="52" y="226" class="subtitle">{safe_subtitle}</text>
          {footer}
          <rect x="52" y="442" width="220" height="24" rx="12" fill="{accent}" opacity="0.7" />
          <text x="52" y="512" class="footer">Media de prototipo generada por el backend</text>
          <style>
            .header {{
              fill: rgba(255,255,255,0.72);
              font: 600 18px 'Bahnschrift', 'Trebuchet MS', sans-serif;
              letter-spacing: 3px;
            }}
            .title {{
              fill: #ffffff;
              font: 700 50px 'Bahnschrift', 'Trebuchet MS', sans-serif;
            }}
            .subtitle {{
              fill: rgba(255,255,255,0.82);
              font: 500 24px 'Aptos', 'Segoe UI', sans-serif;
            }}
            .meta {{
              fill: rgba(255,255,255,0.72);
              font: 500 20px 'Aptos', 'Segoe UI', sans-serif;
            }}
            .footer {{
              fill: rgba(255,255,255,0.42);
              font: 500 18px 'Aptos', 'Segoe UI', sans-serif;
            }}
          </style>
        </svg>
        """
        return textwrap.dedent(svg).strip().encode("utf-8")


media_store = MediaStore()
