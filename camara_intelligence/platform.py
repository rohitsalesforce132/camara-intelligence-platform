"""
CAMARA Developer Intelligence Platform
=======================================
Combines the CAMARA API Mock Server with the Demand-Driven Context Engine.

When developers test against the mock, the system:
1. Captures every API call, failure, and misunderstanding
2. Identifies knowledge gaps (wrong params, missing fields, confusion)
3. Builds a CAMARA-specific knowledge base from actual developer failures
4. Serves contextual help via /help endpoints

The result: a self-documenting API testing platform that gets smarter with every dev who uses it.

Run: uvicorn camara_intelligence.platform:app --reload --port 8093
"""

from __future__ import annotations

import uuid
import json
import enum
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import (
    create_engine, String, Integer, Float, DateTime, Boolean, Text,
    Enum as SAEnum, ForeignKey,
)
from sqlalchemy.orm import (
    declarative_base, sessionmaker, Session, Mapped, mapped_column, relationship,
)

# ─── Database ──────────────────────────────────────────────────────────────────

DATABASE_URL = "sqlite:///./camara_intelligence.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


# ─── Enums ─────────────────────────────────────────────────────────────────────

class ApiName(str, enum.Enum):
    SIM_SWAP = "sim_swap"
    NUMBER_VERIFICATION = "number_verification"
    DEVICE_STATUS = "device_status"
    CARRIER_BILLING = "carrier_billing"
    QOS = "qos"


class CallStatus(str, enum.Enum):
    SUCCESS = "success"
    CLIENT_ERROR = "client_error"  # 4xx — developer mistake
    SERVER_ERROR = "server_error"
    NOT_FOUND = "not_found"


class GapType(str, enum.Enum):
    WRONG_PARAMS = "wrong_params"           # Incorrect request body
    MISSING_FIELD = "missing_field"         # Required field omitted
    WRONG_FORMAT = "wrong_format"           # E.164 format, ISO date, etc.
    WRONG_ENDPOINT = "wrong_endpoint"       # Called wrong URL
    AUTH_ISSUE = "auth_issue"               # API key / OAuth confusion
    RESPONSE_MISUNDERSTAND = "response_misunderstand"  # Misinterpreted response
    RATE_LIMIT = "rate_limit"
    SCENARIO_CONFUSION = "scenario_confusion"  # Didn't understand test scenarios


class HelpCategory(str, enum.Enum):
    API_REFERENCE = "api_reference"
    REQUEST_FORMAT = "request_format"
    RESPONSE_FORMAT = "response_format"
    ERROR_CODES = "error_codes"
    AUTHENTICATION = "authentication"
    WORKFLOW = "workflow"
    TESTING = "testing"
    SCENARIO = "scenario"


# ─── Models ────────────────────────────────────────────────────────────────────

class Developer(Base):
    __tablename__ = "developers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    team: Mapped[str] = mapped_column(String(100), default="")
    api_key: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: uuid.uuid4().hex)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    calls: Mapped[list["ApiCall"]] = relationship(back_populates="developer", cascade="all, delete-orphan")


class ApiCall(Base):
    __tablename__ = "api_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    developer_id: Mapped[str] = mapped_column(String(36), ForeignKey("developers.id"), nullable=True)
    api_name: Mapped[str] = mapped_column(String(50), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(10), default="POST")
    request_body: Mapped[str] = mapped_column(Text, default="")
    response_code: Mapped[int] = mapped_column(Integer, default=200)
    response_body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(SAEnum(CallStatus), default=CallStatus.SUCCESS)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    developer: Mapped["Developer"] = relationship(back_populates="calls")
    gaps: Mapped[list["KnowledgeGap"]] = relationship(back_populates="call", cascade="all, delete-orphan")


class KnowledgeGap(Base):
    __tablename__ = "knowledge_gaps"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    call_id: Mapped[str] = mapped_column(String(36), ForeignKey("api_calls.id"), nullable=True)
    api_name: Mapped[str] = mapped_column(String(50), nullable=False)
    gap_type: Mapped[str] = mapped_column(SAEnum(GapType), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    developer_message: Mapped[str] = mapped_column(Text, default="")  # What the dev was trying
    correct_usage: Mapped[str] = mapped_column(Text, default="")  # What they should have done
    frequency: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    call: Mapped["ApiCall"] = relationship(back_populates="gaps")
    articles: Mapped[list["HelpArticle"]] = relationship(
        back_populates="gap", secondary="gap_articles", cascade="all, delete-orphan",
        single_parent=True,
    )


class GapArticle(Base):
    """Many-to-many between gaps and articles."""
    __tablename__ = "gap_articles"
    gap_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_gaps.id", ondelete="CASCADE"), primary_key=True)
    article_id: Mapped[str] = mapped_column(String(36), ForeignKey("help_articles.id", ondelete="CASCADE"), primary_key=True)


class HelpArticle(Base):
    __tablename__ = "help_articles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(SAEnum(HelpCategory), nullable=False)
    api_name: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(String(50), default="auto")  # auto, manual, community
    views: Mapped[int] = mapped_column(Integer, default=0)
    helpful_votes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    gap: Mapped[list["KnowledgeGap"]] = relationship(
        back_populates="articles", secondary="gap_articles",
    )


# ─── Engine ────────────────────────────────────────────────────────────────────

class CamaraIntelligenceEngine:
    """
    Core engine that combines mock API serving with knowledge gap detection.

    When a developer makes an API call:
    1. Log the call with full request/response
    2. If it's a client error (4xx), analyze what went wrong
    3. Match against known gap patterns
    4. Auto-generate help articles for new gaps
    5. Serve contextual help based on the endpoint + error
    """

    # Patterns of common developer mistakes
    ERROR_PATTERNS = {
        (404, "phone_number"): (GapType.WRONG_FORMAT, "Phone number not found — use E.164 format (+ country code)"),
        (404, "not found"): (GapType.WRONG_ENDPOINT, "Endpoint not found — check the API path"),
        (400, "missing"): (GapType.MISSING_FIELD, "Required field missing from request body"),
        (400, "invalid"): (GapType.WRONG_FORMAT, "Invalid field format in request"),
        (410, "inactive"): (GapType.SCENARIO_CONFUSION, "Phone number is inactive — this is a test scenario number"),
        (400, "cannot refund"): (GapType.RESPONSE_MISUNDERSTAND, "Cannot refund a failed/refunded charge"),
        (400, "Unknown scenario"): (GapType.SCENARIO_CONFUSION, "Invalid test scenario name"),
        (422, "validation"): (GapType.WRONG_PARAMS, "Request body validation failed"),
    }

    # Auto-generated help content for each API
    API_HELP = {
        ApiName.SIM_SWAP: {
            "endpoint": "/camara/v1/sim-swap/check",
            "method": "POST",
            "required_fields": ["phone_number"],
            "optional_fields": ["max_age_hours (default: 240)"],
            "example": {"phone_number": "+919876543210", "max_age_hours": 72},
            "response_fields": ["swapped (bool)", "sim_swap_date (ISO 8601 or null)", "sim_swap_count (int)"],
            "common_mistakes": [
                "Using phone number without country code (+91...)",
                "Setting max_age_hours too low to catch recent swaps",
                "Not checking sim_swap_count — high count indicates fraud",
            ],
        },
        ApiName.NUMBER_VERIFICATION: {
            "endpoint": "/camara/v1/number-verification/verify",
            "method": "POST",
            "required_fields": ["phone_number"],
            "example": {"phone_number": "+919876543210"},
            "response_fields": ["verification_status", "carrier_name", "country"],
        },
        ApiName.DEVICE_STATUS: {
            "endpoint": "/camara/v1/device-status",
            "method": "POST",
            "required_fields": ["phone_number"],
            "optional_fields": ["include_roaming (bool, default: false)"],
            "example": {"phone_number": "+919876543210", "include_roaming": True},
            "response_fields": ["status (CONNECTED|ROAMING|OFFLINE|UNKNOWN)", "network_type", "roaming (object or null)", "data_speed_mbps"],
        },
        ApiName.CARRIER_BILLING: {
            "endpoint": "/camara/v1/carrier-billing/charge",
            "method": "POST",
            "required_fields": ["phone_number", "amount"],
            "optional_fields": ["currency (default: INR)", "description", "client_correlator (idempotency)"],
            "example": {"phone_number": "+919876543210", "amount": 49.99, "currency": "INR"},
            "response_fields": ["id", "status (completed|failed)", "amount", "currency"],
            "common_mistakes": [
                "High fraud score numbers will reject charges",
                "Always use client_correlator for idempotency",
                "Refunds only work on completed charges, not failed ones",
            ],
        },
        ApiName.QOS: {
            "endpoint": "/camara/v1/qos/request",
            "method": "POST",
            "required_fields": ["phone_number"],
            "optional_fields": ["qos_profile (QOS_S|M|L|E, default: QOS_E)", "duration (seconds, default: 3600)"],
            "example": {"phone_number": "+919876543210", "qos_profile": "QOS_E", "duration": 7200},
            "response_fields": ["session_id", "status (AVAILABLE|UNAVAILABLE)", "duration_seconds"],
        },
    }

    def __init__(self, db: Session):
        self.db = db

    # ── Developer Management ──

    def register_developer(self, name: str, team: str = "") -> Developer:
        dev = Developer(name=name, team=team)
        self.db.add(dev)
        self.db.commit()
        self.db.refresh(dev)
        return dev

    def get_developer(self, developer_id: str) -> Developer | None:
        return self.db.query(Developer).filter(Developer.id == developer_id).first()

    def get_developer_by_key(self, api_key: str) -> Developer | None:
        return self.db.query(Developer).filter(Developer.api_key == api_key).first()

    # ── Call Logging ──

    def log_call(
        self, api_name: str, endpoint: str, method: str, request_body: str,
        response_code: int, response_body: str, latency_ms: float = 0.0,
        developer_id: str | None = None,
    ) -> ApiCall:
        status = CallStatus.SUCCESS
        if 400 <= response_code < 500:
            status = CallStatus.CLIENT_ERROR
        elif response_code >= 500:
            status = CallStatus.SERVER_ERROR
        elif response_code == 404 and "not found" in response_body.lower():
            status = CallStatus.NOT_FOUND

        call = ApiCall(
            developer_id=developer_id,
            api_name=api_name,
            endpoint=endpoint,
            method=method,
            request_body=request_body,
            response_code=response_code,
            response_body=response_body,
            status=status,
            latency_ms=latency_ms,
        )
        self.db.add(call)

        # Auto-detect knowledge gaps on client errors
        if status in (CallStatus.CLIENT_ERROR, CallStatus.NOT_FOUND):
            self._detect_gap(call)

        self.db.commit()
        self.db.refresh(call)
        return call

    def _detect_gap(self, call: ApiCall) -> KnowledgeGap | None:
        """Analyze a failed API call and create/update a knowledge gap."""
        gap_type = GapType.WRONG_PARAMS
        description = f"API call to {call.endpoint} returned {call.response_code}"
        correct_usage = ""

        # Match against known patterns
        body_lower = call.response_body.lower()
        for (code, keyword), (gt, desc) in self.ERROR_PATTERNS.items():
            if call.response_code == code and keyword in body_lower:
                gap_type = gt
                description = desc
                break

        # Generate correct usage from API help
        try:
            api_enum = ApiName(call.api_name)
            help_data = self.API_HELP.get(api_enum, {})
            correct_usage = json.dumps(help_data.get("example", {}), indent=2)
        except ValueError:
            pass

        # Check for existing gap
        existing = self.db.query(KnowledgeGap).filter(
            KnowledgeGap.api_name == call.api_name,
            KnowledgeGap.gap_type == gap_type,
            KnowledgeGap.description == description,
        ).first()

        if existing:
            existing.frequency += 1
            existing.last_seen = datetime.now(timezone.utc)
            self.db.commit()
            return existing

        gap = KnowledgeGap(
            call_id=call.id,
            api_name=call.api_name,
            gap_type=gap_type,
            description=description,
            developer_message=call.request_body[:500],
            correct_usage=correct_usage,
        )
        self.db.add(gap)
        self.db.commit()
        self.db.refresh(gap)

        # Auto-generate help article for new gap types
        self._auto_generate_article(gap)

        return gap

    def _auto_generate_article(self, gap: KnowledgeGap):
        """Auto-generate a help article for a knowledge gap."""
        try:
            api_enum = ApiName(gap.api_name)
        except ValueError:
            return

        help_data = self.API_HELP.get(api_enum)
        if not help_data:
            return

        # Check if article already exists for this API + category
        existing = self.db.query(HelpArticle).filter(
            HelpArticle.api_name == gap.api_name,
            HelpArticle.category == HelpCategory.ERROR_CODES,
        ).first()
        if existing:
            # Link gap to existing article
            if existing not in gap.articles:
                gap.articles.append(existing)
            self.db.commit()
            return

        category = HelpCategory.ERROR_CODES
        if gap.gap_type == GapType.WRONG_PARAMS:
            category = HelpCategory.REQUEST_FORMAT
        elif gap.gap_type == GapType.RESPONSE_MISUNDERSTAND:
            category = HelpCategory.RESPONSE_FORMAT
        elif gap.gap_type == GapType.SCENARIO_CONFUSION:
            category = HelpCategory.TESTING

        content_parts = [
            f"# {api_enum.value.replace('_', ' ').title()} — {gap.gap_type.value.replace('_', ' ').title()}\n",
            f"## Common Issue\n{gap.description}\n",
            f"## Correct Request Format\n```json\n{json.dumps(help_data.get('example', {}), indent=2)}\n```\n",
            f"## Endpoint\n`{help_data.get('method', 'POST')} {help_data.get('endpoint', '')}`\n",
            f"## Required Fields\n" + "\n".join(f"- `{f}`" for f in help_data.get("required_fields", [])) + "\n",
        ]

        if help_data.get("optional_fields"):
            content_parts.append("## Optional Fields\n" + "\n".join(f"- `{f}`" for f in help_data["optional_fields"]) + "\n")

        if help_data.get("common_mistakes"):
            content_parts.append("## Common Mistakes\n" + "\n".join(f"- ⚠️ {m}" for m in help_data["common_mistakes"]) + "\n")

        if gap.correct_usage:
            content_parts.append(f"## Correct Usage\n```json\n{gap.correct_usage}\n```\n")

        article = HelpArticle(
            title=f"{api_enum.value.replace('_', ' ').title()}: Fixing {gap.gap_type.value.replace('_', ' ')} errors",
            content="\n".join(content_parts),
            category=category,
            api_name=gap.api_name,
            source="auto",
        )
        self.db.add(article)
        gap.articles.append(article)
        self.db.commit()

    # ── Help & Knowledge ──

    def get_api_help(self, api_name: str) -> dict:
        """Get help documentation for a specific API."""
        try:
            api_enum = ApiName(api_name)
        except ValueError:
            raise HTTPException(400, f"Unknown API: {api_name}. Available: {[a.value for a in ApiName]}")

        help_data = self.API_HELP.get(api_enum, {})
        articles = self.db.query(HelpArticle).filter(HelpArticle.api_name == api_name).all()

        return {
            "api": api_name,
            "reference": help_data,
            "help_articles": [
                {"id": a.id, "title": a.title, "category": a.category.value, "views": a.views}
                for a in articles
            ],
            "known_gaps": self._get_api_gaps(api_name),
        }

    def get_help_article(self, article_id: str) -> HelpArticle:
        article = self.db.query(HelpArticle).filter(HelpArticle.id == article_id).first()
        if not article:
            raise HTTPException(404, f"Article {article_id} not found")
        article.views += 1
        self.db.commit()
        self.db.refresh(article)
        return article

    def get_contextual_help(self, endpoint: str, error_code: int | None = None) -> list[dict]:
        """Get help relevant to a specific endpoint and optional error code."""
        # Determine API name from endpoint
        api_name = None
        for api in ApiName:
            if api.value.replace("_", "-") in endpoint or api.value in endpoint:
                api_name = api.value
                break

        if not api_name:
            return []

        articles = self.db.query(HelpArticle).filter(HelpArticle.api_name == api_name)
        if error_code:
            articles = articles.filter(HelpArticle.category == HelpCategory.ERROR_CODES)

        return [
            {"id": a.id, "title": a.title, "category": a.category.value, "views": a.views}
            for a in articles.all()
        ]

    def _get_api_gaps(self, api_name: str) -> list[dict]:
        gaps = self.db.query(KnowledgeGap).filter(
            KnowledgeGap.api_name == api_name
        ).order_by(KnowledgeGap.frequency.desc()).all()
        return [
            {
                "id": g.id,
                "type": g.gap_type.value,
                "description": g.description,
                "frequency": g.frequency,
                "correct_usage": g.correct_usage[:200] if g.correct_usage else "",
            }
            for g in gaps
        ]

    # ── Analytics ──

    def get_developer_analytics(self, developer_id: str) -> dict:
        dev = self.get_developer(developer_id)
        if not dev:
            raise HTTPException(404, "Developer not found")

        calls = dev.calls
        total = len(calls)
        if total == 0:
            return {"developer": dev.name, "total_calls": 0}

        errors = [c for c in calls if c.status != CallStatus.SUCCESS]
        api_dist = {}
        for c in calls:
            api_dist[c.api_name] = api_dist.get(c.api_name, 0) + 1

        return {
            "developer": dev.name,
            "team": dev.team,
            "total_calls": total,
            "errors": len(errors),
            "success_rate": (total - len(errors)) / total,
            "api_distribution": api_dist,
            "most_used_api": max(api_dist, key=api_dist.get) if api_dist else None,
            "common_errors": self._get_developer_errors(developer_id),
        }

    def _get_developer_errors(self, developer_id: str) -> list[dict]:
        error_calls = self.db.query(ApiCall).filter(
            ApiCall.developer_id == developer_id,
            ApiCall.status != CallStatus.SUCCESS,
        ).all()

        error_types = {}
        for c in error_calls:
            key = f"{c.api_name}:{c.response_code}"
            if key not in error_types:
                error_types[key] = {"api": c.api_name, "code": c.response_code, "count": 0}
            error_types[key]["count"] += 1

        return sorted(error_types.values(), key=lambda x: x["count"], reverse=True)[:5]

    def get_platform_analytics(self) -> dict:
        total_calls = self.db.query(ApiCall).count()
        total_gaps = self.db.query(KnowledgeGap).count()
        total_articles = self.db.query(HelpArticle).count()
        total_devs = self.db.query(Developer).count()

        # Top gaps
        top_gaps = self.db.query(KnowledgeGap).order_by(KnowledgeGap.frequency.desc()).limit(10).all()

        # API popularity
        api_calls = {}
        for call in self.db.query(ApiCall).all():
            api_calls[call.api_name] = api_calls.get(call.api_name, 0) + 1

        return {
            "total_developers": total_devs,
            "total_api_calls": total_calls,
            "total_knowledge_gaps": total_gaps,
            "total_help_articles": total_articles,
            "api_popularity": api_calls,
            "top_knowledge_gaps": [
                {"api": g.api_name, "type": g.gap_type.value, "description": g.description, "frequency": g.frequency}
                for g in top_gaps
            ],
            "knowledge_coverage": self._get_coverage(),
        }

    def _get_coverage(self) -> dict:
        """How well does the knowledge base cover each API?"""
        coverage = {}
        for api in ApiName:
            gaps = self.db.query(KnowledgeGap).filter(KnowledgeGap.api_name == api.value).count()
            articles = self.db.query(HelpArticle).filter(HelpArticle.api_name == api.value).count()
            coverage[api.value] = {"gaps_found": gaps, "articles_available": articles}
        return coverage

    def vote_helpful(self, article_id: str) -> HelpArticle:
        article = self.db.query(HelpArticle).filter(HelpArticle.id == article_id).first()
        if not article:
            raise HTTPException(404, "Article not found")
        article.helpful_votes += 1
        self.db.commit()
        return article

    def create_manual_article(self, title: str, content: str, api_name: str, category: str) -> HelpArticle:
        article = HelpArticle(
            title=title, content=content, api_name=api_name,
            category=HelpCategory(category), source="manual",
        )
        self.db.add(article)
        self.db.commit()
        self.db.refresh(article)
        return article


# ─── FastAPI Application ───────────────────────────────────────────────────────

app = FastAPI(
    title="CAMARA Developer Intelligence Platform",
    description="""
    **Self-documenting CAMARA API testing platform.**
    
    Combines mock API serving with knowledge gap detection.
    Every developer mistake makes the platform smarter.
    
    **Flow:**
    1. Developers test against mock APIs
    2. System captures failures and identifies knowledge gaps
    3. Auto-generates help articles for common mistakes
    4. New developers get contextual help based on accumulated knowledge
    
    **Endpoints:**
    - `/dev/register` — Register as a developer
    - `/dev/{id}/analytics` — Your testing stats
    - `/calls` — Log API calls (or use middleware)
    - `/help/{api}` — Get help for a CAMARA API
    - `/help/article/{id}` — Read a help article
    - `/help/contextual` — Get help for your current situation
    - `/analytics/platform` — Platform-wide intelligence
    """,
    version="1.0.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_engine(db: Session = Depends(get_db)) -> CamaraIntelligenceEngine:
    return CamaraIntelligenceEngine(db)


# ── Pydantic Schemas ──

class DevRegister(BaseModel):
    name: str = Field(..., min_length=1)
    team: str = ""


class CallLog(BaseModel):
    api_name: str
    endpoint: str
    method: str = "POST"
    request_body: str = ""
    response_code: int
    response_body: str = ""
    latency_ms: float = 0.0


class ManualArticle(BaseModel):
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    api_name: str
    category: str = "workflow"


# ── API Routes ──

@app.post("/dev/register", tags=["Developer"])
def register_developer(data: DevRegister, eng: CamaraIntelligenceEngine = Depends(get_engine)):
    dev = eng.register_developer(data.name, data.team)
    return {"id": dev.id, "name": dev.name, "api_key": dev.api_key}


@app.get("/dev/{developer_id}/analytics", tags=["Developer"])
def developer_analytics(developer_id: str, eng: CamaraIntelligenceEngine = Depends(get_engine)):
    return eng.get_developer_analytics(developer_id)


@app.post("/calls", tags=["Call Logging"])
def log_call(data: CallLog, eng: CamaraIntelligenceEngine = Depends(get_engine)):
    call = eng.log_call(
        data.api_name, data.endpoint, data.method, data.request_body,
        data.response_code, data.response_body, data.latency_ms,
    )
    return {
        "id": call.id,
        "status": call.status.value,
        "gap_detected": len(call.gaps) > 0,
        "help_available": len(call.gaps) > 0 and any(g.articles for g in call.gaps),
    }


@app.get("/help/{api_name}", tags=["Help"])
def api_help(api_name: str, eng: CamaraIntelligenceEngine = Depends(get_engine)):
    return eng.get_api_help(api_name)


@app.get("/help/article/{article_id}", tags=["Help"])
def read_article(article_id: str, eng: CamaraIntelligenceEngine = Depends(get_engine)):
    article = eng.get_help_article(article_id)
    return {"id": article.id, "title": article.title, "content": article.content, "views": article.views, "helpful": article.helpful_votes}


@app.get("/help/contextual", tags=["Help"])
def contextual_help(endpoint: str, error_code: int | None = None, eng: CamaraIntelligenceEngine = Depends(get_engine)):
    return eng.get_contextual_help(endpoint, error_code)


@app.post("/help/article/{article_id}/helpful", tags=["Help"])
def vote_helpful(article_id: str, eng: CamaraIntelligenceEngine = Depends(get_engine)):
    article = eng.vote_helpful(article_id)
    return {"helpful_votes": article.helpful_votes}


@app.post("/help/articles", tags=["Help"])
def create_article(data: ManualArticle, eng: CamaraIntelligenceEngine = Depends(get_engine)):
    article = eng.create_manual_article(data.title, data.content, data.api_name, data.category)
    return {"id": article.id, "title": article.title}


@app.get("/analytics/platform", tags=["Analytics"])
def platform_analytics(eng: CamaraIntelligenceEngine = Depends(get_engine)):
    return eng.get_platform_analytics()
