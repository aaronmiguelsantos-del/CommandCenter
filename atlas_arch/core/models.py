from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]
RAG = Literal["green", "yellow", "red"]


class SystemContract(BaseModel):
    system_id: str
    name: str
    version: str
    owner: str = "Aaron"
    purpose: str
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    primitives_used: List[str] = Field(default_factory=list)
    invariants: List[str] = Field(default_factory=list)
    failure_modes: List[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class EventRecord(BaseModel):
    ts: datetime = Field(default_factory=datetime.utcnow)
    system_id: str
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class DecisionRecord(BaseModel):
    ts: datetime = Field(default_factory=datetime.utcnow)
    system_id: str
    context: Dict[str, Any] = Field(default_factory=dict)
    options: List[Dict[str, Any]] = Field(default_factory=list)
    decision: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    rationale: str = ""
    next_action: str = ""
    kill_switch: Optional[Dict[str, Any]] = None


class MetricSample(BaseModel):
    ts: datetime = Field(default_factory=datetime.utcnow)
    system_id: str
    metric: str
    value: float
    unit: str = ""


class AlertRecord(BaseModel):
    ts: datetime = Field(default_factory=datetime.utcnow)
    system_id: str
    severity: Severity
    title: str
    message: str
    tags: List[str] = Field(default_factory=list)


class HealthReport(BaseModel):
    ts: datetime = Field(default_factory=datetime.utcnow)
    overall_score: float
    rag: RAG
    dimension_scores: Dict[str, float]
    key_issues: List[str]
    recommended_fixes: List[str]
