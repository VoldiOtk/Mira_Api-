from __future__ import annotations
import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, String, Text, JSON,
    ForeignKey,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    organization = Column(String(255))
    stripe_customer_id = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    api_keys = relationship("ApiKey", back_populates="client", cascade="all, delete-orphan")


class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    key_prefix = Column(String(16), index=True)
    key_hash = Column(String(255), nullable=False)
    name = Column(String(128))
    last_four = Column(String(8))
    is_active = Column(Boolean, default=True)
    quota_used = Column(Integer, default=0)
    quota_total = Column(Integer, default=10000)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    client = relationship("Client", back_populates="api_keys")


class SignLanguageModel(Base):
    __tablename__ = "sign_language_models"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255))
    slug = Column(String(64), unique=True)
    language_code = Column(String(16), index=True)
    status = Column(String(32), default="ready")
    model_path = Column(String(512))
    artifact_path = Column(String(512))
    is_published = Column(Boolean, default=False)
    published_at = Column(DateTime, nullable=True)
    visibility = Column(String(32), default="public")
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True)
    training_job_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Dataset(Base):
    __tablename__ = "datasets"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    language_code = Column(String(16))
    path = Column(String(512))
    status = Column(String(32), default="ready")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class TrainingJob(Base):
    __tablename__ = "training_jobs"
    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, ForeignKey("sign_language_models.id", ondelete="SET NULL"), nullable=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id", ondelete="RESTRICT"), nullable=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True)
    language_code = Column(String(16), nullable=False)
    status = Column(String(32), default="queued")
    celery_task_id = Column(String(255))
    params = Column(JSON)
    progress = Column(Float)
    metrics = Column(JSON)
    log_output = Column(Text)
    error_message = Column(Text)
    target_model_name = Column(String(255))
    target_model_version = Column(String(64))
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class UsageLog(Base):
    __tablename__ = "usage_logs"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True)
    endpoint = Column(String(255))
    method = Column(String(16))
    model_id = Column(Integer, nullable=True)
    status_code = Column(Integer)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class RecognitionFeedback(Base):
    __tablename__ = "recognition_feedbacks"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True)
    model_id = Column(Integer, ForeignKey("sign_language_models.id", ondelete="SET NULL"), nullable=True)
    session_id = Column(String(64))
    predicted_label = Column(String(128))
    correct_label = Column(String(128))
    confidence = Column(Float)
    review_status = Column(String(32), default="pending")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(64), unique=True)
    language_name = Column(String(128))
    language_code = Column(String(16))
    country_or_region = Column(String(128))
    description = Column(Text)
    root_path = Column(String(512), nullable=False)
    is_legacy = Column(Boolean, default=False)
    status = Column(String(32), default="detected")
    version = Column(String(64))
    labels_file_path = Column(String(512))
    metadata_file_path = Column(String(512))
    total_files = Column(Integer)
    total_images = Column(Integer)
    total_videos = Column(Integer)
    total_classes = Column(Integer)
    total_size = Column(Integer)
    scan_report = Column(JSON)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_scanned_at = Column(DateTime, nullable=True)
    created_by = Column(String(128))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_type = Column(String(32), nullable=False)
    actor_id = Column(Integer)
    action = Column(String(128), nullable=False)
    target_type = Column(String(64))
    target_id = Column(Integer)
    details = Column(JSON)
    ip_address = Column(String(64))
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_number = Column(String(64), unique=True, nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    client_name = Column(String(255), nullable=False)
    client_email = Column(String(255), nullable=False)
    issue_date = Column(DateTime)
    due_date = Column(DateTime)
    status = Column(String(32), nullable=False, default="pending")
    vat_rate = Column(Float, nullable=False, default=20.0)
    notes = Column(Text)
    items = Column(JSON)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


class ModelAccess(Base):
    __tablename__ = "model_access"
    id = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(Integer, ForeignKey("sign_language_models.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    granted_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
