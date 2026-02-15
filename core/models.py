from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

try:
    from pydantic import BaseModel, ConfigDict, Field  # type: ignore

    HAS_PYDANTIC = True
except ImportError:  # pragma: no cover
    BaseModel = object  # type: ignore
    ConfigDict = dict  # type: ignore
    Field = None  # type: ignore
    HAS_PYDANTIC = False


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require_non_empty(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_range(name: str, value: float, min_val: float, max_val: float) -> None:
    if value < min_val or value > max_val:
        raise ValueError(f"{name} must be between {min_val} and {max_val}")


if HAS_PYDANTIC:
    class Contract(BaseModel):
        model_config = ConfigDict(extra="forbid")

        contract_id: str
        system_id: str = Field(min_length=1)
        name: str = Field(min_length=1)
        version: str = "0.1.0"
        status: str = "active"
        created_at: str = Field(default_factory=utc_now_iso)
        updated_at: str = Field(default_factory=utc_now_iso)


    class Event(BaseModel):
        model_config = ConfigDict(extra="forbid")

        event_id: str
        system_id: str = Field(min_length=1)
        event_type: str = Field(min_length=1)
        ts: str = Field(default_factory=utc_now_iso)
        payload: dict[str, Any] = Field(default_factory=dict)


    class Decision(BaseModel):
        model_config = ConfigDict(extra="forbid")

        decision_id: str
        system_id: str = Field(min_length=1)
        title: str = Field(min_length=1)
        rationale: str = Field(min_length=1)
        ts: str = Field(default_factory=utc_now_iso)


    class Metric(BaseModel):
        model_config = ConfigDict(extra="forbid")

        metric_id: str
        system_id: str = Field(min_length=1)
        name: str = Field(min_length=1)
        value: float
        ts: str = Field(default_factory=utc_now_iso)


    class Alert(BaseModel):
        model_config = ConfigDict(extra="forbid")

        alert_id: str
        system_id: str = Field(min_length=1)
        severity: str
        message: str = Field(min_length=1)
        ts: str = Field(default_factory=utc_now_iso)


    class Health(BaseModel):
        model_config = ConfigDict(extra="forbid")

        ts: str = Field(default_factory=utc_now_iso)
        contracts_count: int = Field(ge=0)
        events_count: int = Field(ge=0)
        schema_count: int = Field(ge=0)
        invariant_count: int = Field(ge=0)
        score_contracts: float = Field(ge=0, le=100)
        score_events: float = Field(ge=0, le=100)
        score_primitives: float = Field(ge=0, le=100)
        score_total: float = Field(ge=0, le=100)
else:
    @dataclass
    class _CompatBase:
        def model_dump(self) -> dict[str, Any]:
            return self.__dict__.copy()


    @dataclass
    class Contract(_CompatBase):
        contract_id: str
        system_id: str
        name: str
        version: str = "0.1.0"
        status: str = "active"
        created_at: str = field(default_factory=utc_now_iso)
        updated_at: str = field(default_factory=utc_now_iso)

        def __post_init__(self) -> None:
            _require_non_empty("contract_id", self.contract_id)
            _require_non_empty("system_id", self.system_id)
            _require_non_empty("name", self.name)
            if self.status not in {"active", "inactive"}:
                raise ValueError("status must be active or inactive")


    @dataclass
    class Event(_CompatBase):
        event_id: str
        system_id: str
        event_type: str
        ts: str = field(default_factory=utc_now_iso)
        payload: dict[str, Any] = field(default_factory=dict)

        def __post_init__(self) -> None:
            _require_non_empty("event_id", self.event_id)
            _require_non_empty("system_id", self.system_id)
            _require_non_empty("event_type", self.event_type)


    @dataclass
    class Decision(_CompatBase):
        decision_id: str
        system_id: str
        title: str
        rationale: str
        ts: str = field(default_factory=utc_now_iso)

        def __post_init__(self) -> None:
            _require_non_empty("decision_id", self.decision_id)
            _require_non_empty("system_id", self.system_id)
            _require_non_empty("title", self.title)
            _require_non_empty("rationale", self.rationale)


    @dataclass
    class Metric(_CompatBase):
        metric_id: str
        system_id: str
        name: str
        value: float
        ts: str = field(default_factory=utc_now_iso)

        def __post_init__(self) -> None:
            _require_non_empty("metric_id", self.metric_id)
            _require_non_empty("system_id", self.system_id)
            _require_non_empty("name", self.name)


    @dataclass
    class Alert(_CompatBase):
        alert_id: str
        system_id: str
        severity: str
        message: str
        ts: str = field(default_factory=utc_now_iso)

        def __post_init__(self) -> None:
            _require_non_empty("alert_id", self.alert_id)
            _require_non_empty("system_id", self.system_id)
            if self.severity not in {"low", "medium", "high"}:
                raise ValueError("severity must be low, medium, or high")
            _require_non_empty("message", self.message)


    @dataclass
    class Health(_CompatBase):
        contracts_count: int
        events_count: int
        schema_count: int
        invariant_count: int
        score_contracts: float
        score_events: float
        score_primitives: float
        score_total: float
        ts: str = field(default_factory=utc_now_iso)

        def __post_init__(self) -> None:
            for key in ["contracts_count", "events_count", "schema_count", "invariant_count"]:
                if getattr(self, key) < 0:
                    raise ValueError(f"{key} must be >= 0")
            _require_range("score_contracts", self.score_contracts, 0, 100)
            _require_range("score_events", self.score_events, 0, 100)
            _require_range("score_primitives", self.score_primitives, 0, 100)
            _require_range("score_total", self.score_total, 0, 100)
