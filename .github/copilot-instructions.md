# GitHub Copilot Instructions

> **Purpose:** Help GitHub Copilot understand this codebase and generate better suggestions.

---

## Project Overview

**CAMARA Developer Intelligence Platform** — A self-learning API testing platform that captures developer mistakes, auto-generates help articles, and turns individual failures into collective knowledge.

**Key Concept:** Every failed API call (4xx error) is analyzed to detect knowledge gaps. These gaps are used to auto-generate help articles that help future developers avoid the same mistakes.

---

## Architecture

### Three-Layer Design

1. **FastAPI Application Layer** (`platform.py`)
   - RESTful endpoints for developers, calls, help, analytics
   - Request validation via Pydantic
   - Auto-generated OpenAPI docs

2. **Intelligence Engine** (`CamaraIntelligenceEngine` class)
   - Core business logic
   - Knowledge gap detection via pattern matching
   - Auto article generation
   - Analytics computation

3. **Database Layer** (SQLite + SQLAlchemy ORM)
   - Tables: `Developer`, `ApiCall`, `KnowledgeGap`, `HelpArticle`, `GapArticle` (junction)
   - Relationships: 1-to-many (Developer → ApiCall → KnowledgeGap), many-to-many (KnowledgeGap ↔ HelpArticle)

### Data Flow

```
Developer makes API call → Log to api_calls table
    → If 4xx error → Detect gap via ERROR_PATTERNS
        → Create/update KnowledgeGap
        → Auto-generate HelpArticle (if new gap type)
            → Link gap to article via GapArticle
```

---

## Code Conventions

### Naming

- **Classes:** `PascalCase` (e.g., `CamaraIntelligenceEngine`, `KnowledgeGap`)
- **Functions/Methods:** `snake_case` (e.g., `log_call`, `_detect_gap`)
- **Constants:** `UPPER_SNAKE_CASE` (e.g., `ERROR_PATTERNS`, `API_HELP`)
- **Private methods:** Prefix with `_` (e.g., `_detect_gap`, `_auto_generate_article`)

### Docstrings (Google Style)

```python
def log_call(
    self, api_name: str, endpoint: str, method: str, request_body: str,
    response_code: int, response_body: str, latency_ms: float = 0.0,
    developer_id: str | None = None,
) -> ApiCall:
    """
    Log an API call to the database.

    If the call failed (4xx error), automatically detects knowledge gaps
    and generates help articles.

    Args:
        api_name: The CAMARA API name (e.g., "sim_swap", "carrier_billing").
        endpoint: The API endpoint path.
        method: HTTP method (default: "POST").
        request_body: JSON request body as a string.
        response_code: HTTP response code.
        response_body: JSON response body as a string.
        latency_ms: Request latency in milliseconds.
        developer_id: Optional developer ID for attribution.

    Returns:
        The created ApiCall object with populated fields.
    """
```

### Type Hints

- **Always use type hints** for function arguments and return values
- **Use `| None`** for optional types (Python 3.10+ style)
- **Use `list[Type]`** instead of `List[Type]` (PEP 585)
- **Use enums** for fixed sets of values (e.g., `ApiName`, `GapType`)

---

## Key Patterns

### 1. Database Session Management

```python
def get_db():
    """FastAPI dependency for database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_engine(db: Session = Depends(get_db)) -> CamaraIntelligenceEngine:
    """FastAPI dependency for intelligence engine."""
    return CamaraIntelligenceEngine(db)
```

### 2. Knowledge Gap Detection

```python
def _detect_gap(self, call: ApiCall) -> KnowledgeGap | None:
    """Analyze a failed API call and create/update a knowledge gap."""
    gap_type = GapType.WRONG_PARAMS
    description = f"API call to {call.endpoint} returned {call.response_code}"

    # Match against known patterns
    body_lower = call.response_body.lower()
    for (code, keyword), (gt, desc) in self.ERROR_PATTERNS.items():
        if call.response_code == code and keyword in body_lower:
            gap_type = gt
            description = desc
            break

    # Check for existing gap (deduplication)
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

    # Create new gap
    gap = KnowledgeGap(
        call_id=call.id,
        api_name=call.api_name,
        gap_type=gap_type,
        description=description,
        developer_message=call.request_body[:500],
        correct_usage=self._get_correct_usage(call.api_name),
    )
    self.db.add(gap)
    self.db.commit()
    self.db.refresh(gap)

    # Auto-generate help article
    self._auto_generate_article(gap)
    return gap
```

### 3. Auto Article Generation

```python
def _auto_generate_article(self, gap: KnowledgeGap):
    """Auto-generate a help article for a knowledge gap."""
    try:
        api_enum = ApiName(gap.api_name)
    except ValueError:
        return

    help_data = self.API_HELP.get(api_enum)
    if not help_data:
        return

    # Check for existing article (deduplication)
    existing = self.db.query(HelpArticle).filter(
        HelpArticle.api_name == gap.api_name,
        HelpArticle.category == self._get_category_for_gap(gap.gap_type),
    ).first()
    if existing:
        if existing not in gap.articles:
            gap.articles.append(existing)
        self.db.commit()
        return

    # Generate rich content
    content = self._generate_article_content(gap, help_data)

    article = HelpArticle(
        title=f"{api_enum.value.replace('_', ' ').title()}: {gap.gap_type.value.replace('_', ' ')}",
        content=content,
        category=self._get_category_for_gap(gap.gap_type),
        api_name=gap.api_name,
        source="auto",
    )
    self.db.add(article)
    gap.articles.append(article)
    self.db.commit()
```

### 4. Analytics Query Pattern

```python
def get_platform_analytics(self) -> dict:
    """Get platform-wide analytics."""
    total_calls = self.db.query(ApiCall).count()
    total_gaps = self.db.query(KnowledgeGap).count()
    total_articles = self.db.query(HelpArticle).count()
    total_devs = self.db.query(Developer).count()

    # Top gaps (by frequency)
    top_gaps = self.db.query(KnowledgeGap).order_by(
        KnowledgeGap.frequency.desc()
    ).limit(10).all()

    # API popularity (call distribution)
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
            {"api": g.api_name, "type": g.gap_type.value, "frequency": g.frequency}
            for g in top_gaps
        ],
    }
```

---

## Important Constants

### ERROR_PATTERNS

Maps `(response_code, keyword)` tuples to `(gap_type, description)` pairs.

**When adding new patterns:**
- Choose an appropriate `GapType` (see enum)
- Write a clear, actionable description
- Consider edge cases (false positives)

### API_HELP

Hard-coded reference data for all CAMARA APIs.

**Structure per API:**
```python
ApiName.SIM_SWAP: {
    "endpoint": "/camara/v1/sim-swap/check",
    "method": "POST",
    "required_fields": ["phone_number"],
    "optional_fields": ["max_age_hours (default: 240)"],
    "example": {"phone_number": "+919876543210", "max_age_hours": 72},
    "response_fields": ["swapped (bool)", "sim_swap_date", "sim_swap_count (int)"],
    "common_mistakes": [
        "Using phone number without country code (+91...)",
        "Setting max_age_hours too low to catch recent swaps",
        "Not checking sim_swap_count — high count indicates fraud",
    ],
}
```

**When adding new APIs:**
- Follow the structure above
- Include realistic examples
- Add common mistakes from real-world usage

---

## Testing Patterns

### Fixture Usage

```python
@pytest.fixture
def db():
    """In-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = Session(bind=engine)
    yield session
    session.close()

@pytest.fixture
def intel(db):
    """Intelligence engine with test database."""
    return CamaraIntelligenceEngine(db)

@pytest.fixture
def dev(intel):
    """Test developer for convenience."""
    return intel.register_developer("Test Dev", "Team Alpha")
```

### Test Naming

Use descriptive names: `test_{what}_{when}_{expected}`

```python
def test_404_creates_gap(intel):
    """Test that a 404 response creates a knowledge gap."""
    # ...

def test_duplicate_error_increments_gap(intel):
    """Test that duplicate errors increment gap frequency."""
    # ...

def test_success_does_not_create_gap(intel):
    """Test that successful calls don't create gaps."""
    # ...
```

### Integration Tests

Test full user journeys:

```python
def test_developer_learns_from_failures(intel):
    """
    Full journey:
    1. Developer registers
    2. Makes mistakes (wrong format, wrong endpoint)
    3. System captures gaps and generates help
    4. Developer gets contextual help
    5. Makes correct calls
    6. Analytics show improvement
    """
    # ...
```

---

## What Copilot Should Avoid

### ❌ Don't Generate

- **Database migrations** — we don't use Alembic (SQLite schema is auto-created)
- **Authentication logic** — not implemented yet (API keys are just UUIDs)
- **Rate limiting** — not implemented yet
- **Caching** — not implemented yet

### ⚠️ Be Careful With

- **SQLAlchemy queries** — check for N+1 issues, use `.join()` where appropriate
- **JSON parsing** — use `json.loads()` for request/response bodies
- **Datetime handling** — always use `datetime.now(timezone.utc)` for UTC timestamps
- **Enum lookups** — handle `ValueError` when converting strings to enums

### ✅ Safe to Generate

- **Pydantic models** for new endpoints
- **SQLAlchemy models** for new tables
- **FastAPI routes** following existing patterns
- **Test cases** for new functionality
- **Docstrings** for new functions/classes

---

## Quick Reference

### Key Classes

| Class | Purpose | Key Methods |
|-------|---------|-------------|
| `Developer` | Developer accounts | N/A (ORM model) |
| `ApiCall` | Logged API calls | N/A (ORM model) |
| `KnowledgeGap` | Detected gaps | N/A (ORM model) |
| `HelpArticle` | Help documentation | N/A (ORM model) |
| `CamaraIntelligenceEngine` | Core logic | `log_call()`, `get_api_help()`, `get_platform_analytics()` |

### Key Enums

| Enum | Values | Used For |
|------|--------|----------|
| `ApiName` | `SIM_SWAP`, `NUMBER_VERIFICATION`, `DEVICE_STATUS`, `CARRIER_BILLING`, `QOS` | Identifying CAMARA APIs |
| `CallStatus` | `SUCCESS`, `CLIENT_ERROR`, `SERVER_ERROR`, `NOT_FOUND` | Categorizing API call results |
| `GapType` | `WRONG_PARAMS`, `MISSING_FIELD`, `WRONG_FORMAT`, `WRONG_ENDPOINT`, `AUTH_ISSUE`, `RESPONSE_MISUNDERSTAND`, `RATE_LIMIT`, `SCENARIO_CONFUSION` | Categorizing knowledge gaps |
| `HelpCategory` | `API_REFERENCE`, `REQUEST_FORMAT`, `RESPONSE_FORMAT`, `ERROR_CODES`, `AUTHENTICATION`, `WORKFLOW`, `TESTING`, `SCENARIO` | Organizing help articles |

---

**Last Updated:** 2026-05-07
