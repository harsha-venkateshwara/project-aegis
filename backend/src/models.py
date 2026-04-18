from sqlalchemy import (
    String, Text, Float, Integer, Boolean,
    DateTime, ForeignKey, Index, Enum as SAEnum
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional
import enum


class Base(DeclarativeBase):
    pass


class TicketStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"


class TicketPriority(str, enum.Enum):
    p1 = "P1"
    p2 = "P2"
    p3 = "P3"
    p4 = "P4"


class TicketSource(str, enum.Enum):
    chatbot = "chatbot"
    email = "email"
    manual = "manual"
    webhook = "webhook"


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)

    # Classification
    category: Mapped[Optional[str]] = mapped_column(String(100))
    intent: Mapped[Optional[str]] = mapped_column(String(100))
    priority: Mapped[str] = mapped_column(String(10), default="P3")
    confidence: Mapped[Optional[float]] = mapped_column(Float)

    # Routing
    assigned_team: Mapped[Optional[str]] = mapped_column(String(100))
    assigned_to: Mapped[Optional[str]] = mapped_column(String(200))

    # Lifecycle
    status: Mapped[str] = mapped_column(String(50), default="open")
    source: Mapped[str] = mapped_column(String(50), default="manual")
    customer_email: Mapped[Optional[str]] = mapped_column(String(300))
    customer_tier: Mapped[Optional[str]] = mapped_column(String(50))

    # AI metadata
    was_auto_classified: Mapped[bool] = mapped_column(Boolean, default=False)
    classification_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    rag_confidence: Mapped[Optional[float]] = mapped_column(Float)
    escalation_reason: Mapped[Optional[str]] = mapped_column(String(200))
    chatbot_session_id: Mapped[Optional[str]] = mapped_column(String(200))

    # CSAT
    csat_rating: Mapped[Optional[int]] = mapped_column(Integer)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    reminders: Mapped[list["ReminderLog"]] = relationship("ReminderLog", back_populates="ticket")

    __table_args__ = (
        Index("ix_tickets_status_created", "status", "created_at"),
        Index("ix_tickets_category", "category"),
        Index("ix_tickets_assigned_team", "assigned_team"),
    )


class EmailLog(Base):
    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_email: Mapped[str] = mapped_column(String(300))
    subject: Mapped[str] = mapped_column(String(500))
     # first 1000 chars
    body_preview: Mapped[str] = mapped_column(Text)

    detected_intent: Mapped[Optional[str]] = mapped_column(String(100))
    classification_confidence: Mapped[Optional[float]] = mapped_column(Float)
    template_used: Mapped[Optional[str]] = mapped_column(String(200))
     # auto_responded, escalated orfailed
    action: Mapped[str] = mapped_column(String(50)) 
    ticket_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("tickets.id"))
    sendgrid_message_id: Mapped[Optional[str]] = mapped_column(String(200))

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(200))
      # chat_message, email_processed and ticket_created etc
    event_type: Mapped[str] = mapped_column(String(100))

    intent: Mapped[Optional[str]] = mapped_column(String(100))
    confidence: Mapped[Optional[float]] = mapped_column(Float)
      #RESPOND and ESCALATE
    action: Mapped[Optional[str]] = mapped_column(String(50))
    escalation_reason: Mapped[Optional[str]] = mapped_column(String(200))

    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_events_type_created", "event_type", "created_at"),
        Index("ix_events_intent", "intent"),
    )


class KBDocument(Base):
    __tablename__ = "kb_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(500))
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    file_hash: Mapped[str] = mapped_column(String(64))
    category: Mapped[Optional[str]] = mapped_column(String(100))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime)

    __table_args__ = (
        Index("ix_kb_docs_filename", "filename"),
    )


class ReminderLog(Base):
    __tablename__ = "reminder_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(Integer, ForeignKey("tickets.id"))
    urgency: Mapped[str] = mapped_column(String(20))  # YELLOW | ORANGE | RED
    sent_to: Mapped[str] = mapped_column(String(300))
    manager_cc: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="reminders")


class WorkflowRule(Base):
    __tablename__ = "workflow_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text)
    # category, priority and customer_tier
    trigger_field: Mapped[str] = mapped_column(String(100))
    # eq, contains gt   
    trigger_operator: Mapped[str] = mapped_column(String(20)) 
    trigger_value: Mapped[str] = mapped_column(String(200))
         # route, escalate,notify and tag
    action_type: Mapped[str] = mapped_column(String(100))
    # JSON string
    action_params: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
