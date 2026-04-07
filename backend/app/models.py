from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text

from .database import Base, utcnow


class Site(Base):
    __tablename__ = "sites"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    address = Column(String(255), nullable=False, default="")
    status = Column(String(32), nullable=False, default="online")
    last_seen = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Device(Base):
    __tablename__ = "devices"

    id = Column(String(64), primary_key=True)
    site_id = Column(String(64), ForeignKey("sites.id"), nullable=False, index=True)
    type = Column(String(32), nullable=False)
    name = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, default="online")
    last_seen = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    details = Column(JSON, nullable=False, default=dict)


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(String(64), primary_key=True)
    site_id = Column(String(64), ForeignKey("sites.id"), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, default="online")
    snapshot_url = Column(String(255), nullable=True)
    stream_url = Column(String(255), nullable=True)
    last_seen = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class VisitorEvent(Base):
    __tablename__ = "visitor_events"

    id = Column(String(64), primary_key=True)
    site_id = Column(String(64), ForeignKey("sites.id"), nullable=False, index=True)
    visitor_name = Column(String(128), nullable=False)
    unit_to_visit = Column(String(64), nullable=False)
    host_name = Column(String(128), nullable=False)
    id_type = Column(String(64), nullable=False)
    snapshot_url = Column(String(255), nullable=True)
    status = Column(String(32), nullable=False, default="approved")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String(64), primary_key=True)
    code = Column(String(64), nullable=False, index=True)
    site_id = Column(String(64), ForeignKey("sites.id"), nullable=False, index=True)
    source_type = Column(String(32), nullable=False)
    source_id = Column(String(64), nullable=False, index=True)
    severity = Column(String(16), nullable=False)
    message = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="open", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)


class RemoteAction(Base):
    __tablename__ = "remote_actions"

    id = Column(String(64), primary_key=True)
    site_id = Column(String(64), ForeignKey("sites.id"), nullable=False, index=True)
    action_type = Column(String(64), nullable=False, index=True)
    target_id = Column(String(64), nullable=False, index=True)
    command = Column(String(64), nullable=False)
    requested_by = Column(String(128), nullable=False, default="central-operator")
    payload = Column(JSON, nullable=False, default=dict)
    status = Column(String(32), nullable=False, default="pending", index=True)
    result_message = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id = Column(String(64), primary_key=True)
    object_name = Column(String(255), nullable=False, unique=True)
    content_type = Column(String(128), nullable=False)
    category = Column(String(64), nullable=False)
    site_id = Column(String(64), nullable=True, index=True)
    camera_id = Column(String(64), nullable=True, index=True)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    size_bytes = Column(Integer, nullable=False, default=0)
