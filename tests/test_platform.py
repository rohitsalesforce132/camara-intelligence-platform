"""Tests for CAMARA Developer Intelligence Platform."""
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from camara_intelligence.platform import (
    Base, CamaraIntelligenceEngine, Developer, ApiCall, KnowledgeGap, HelpArticle,
    CallStatus, GapType, HelpCategory, ApiName,
)
from fastapi import HTTPException


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = Session(bind=engine)
    yield session
    session.close()


@pytest.fixture
def intel(db):
    return CamaraIntelligenceEngine(db)


@pytest.fixture
def dev(intel):
    return intel.register_developer("Test Dev", "Team Alpha")


# ── Developer Management ──

class TestDeveloper:
    def test_register(self, intel):
        dev = intel.register_developer("Alice", "Payments")
        assert dev.name == "Alice"
        assert dev.api_key is not None
        assert len(dev.api_key) == 32

    def test_get_developer(self, intel, dev):
        found = intel.get_developer(dev.id)
        assert found.name == "Test Dev"

    def test_get_by_api_key(self, intel, dev):
        found = intel.get_developer_by_key(dev.api_key)
        assert found.id == dev.id


# ── Call Logging ──

class TestCallLogging:
    def test_log_successful_call(self, intel, dev):
        call = intel.log_call(
            "sim_swap", "/camara/v1/sim-swap/check", "POST",
            '{"phone_number": "+919876543210"}', 200,
            '{"swapped": false}', 45.0, dev.id,
        )
        assert call.status == CallStatus.SUCCESS
        assert call.response_code == 200

    def test_log_client_error(self, intel, dev):
        call = intel.log_call(
            "sim_swap", "/camara/v1/sim-swap/check", "POST",
            '{"phone": "9876543210"}', 404,
            '{"detail": "Phone number not found in mock database"}', 12.0, dev.id,
        )
        assert call.status == CallStatus.CLIENT_ERROR

    def test_log_without_developer(self, intel):
        call = intel.log_call("device_status", "/camara/v1/device-status", "POST", "{}", 200, "{}")
        assert call.developer_id is None


# ── Knowledge Gap Detection ──

class TestGapDetection:
    def test_404_creates_gap(self, intel):
        intel.log_call(
            "sim_swap", "/camara/v1/sim-swap/check", "POST",
            '{"phone": "bad"}', 404,
            '{"detail": "Phone number not found"}',
        )
        gaps = intel.db.query(KnowledgeGap).all()
        assert len(gaps) >= 1
        assert gaps[0].frequency == 1

    def test_duplicate_error_increments_gap(self, intel):
        for _ in range(3):
            intel.log_call(
                "sim_swap", "/camara/v1/sim-swap/check", "POST",
                '{"phone": "bad"}', 404,
                '{"detail": "Phone number not found"}',
            )
        gaps = intel.db.query(KnowledgeGap).all()
        assert len(gaps) == 1
        assert gaps[0].frequency == 3

    def test_different_errors_create_different_gaps(self, intel):
        intel.log_call("sim_swap", "/camara/v1/sim-swap/check", "POST", "{}", 404,
                       '{"detail": "Phone number not found"}')
        intel.log_call("carrier_billing", "/camara/v1/carrier-billing/charge", "POST", "{}", 400,
                       '{"detail": "Missing required field"}')
        gaps = intel.db.query(KnowledgeGap).all()
        assert len(gaps) == 2

    def test_success_does_not_create_gap(self, intel):
        intel.log_call("sim_swap", "/camara/v1/sim-swap/check", "POST", "{}", 200, '{"ok": true}')
        gaps = intel.db.query(KnowledgeGap).all()
        assert len(gaps) == 0

    def test_inactive_phone_creates_scenario_gap(self, intel):
        intel.log_call(
            "sim_swap", "/camara/v1/sim-swap/check", "POST",
            '{"phone_number": "+919999999999"}', 410,
            '{"detail": "Phone number is inactive"}',
        )
        gaps = intel.db.query(KnowledgeGap).all()
        assert len(gaps) == 1
        assert gaps[0].gap_type == GapType.SCENARIO_CONFUSION


# ── Auto Help Article Generation ──

class TestAutoArticles:
    def test_gap_auto_generates_article(self, intel):
        intel.log_call(
            "sim_swap", "/camara/v1/sim-swap/check", "POST",
            '{"phone": "bad"}', 404,
            '{"detail": "Phone number not found"}',
        )
        articles = intel.db.query(HelpArticle).all()
        assert len(articles) >= 1
        assert "sim_swap" in articles[0].api_name

    def test_article_has_useful_content(self, intel):
        intel.log_call(
            "sim_swap", "/camara/v1/sim-swap/check", "POST",
            '{"phone": "bad"}', 404,
            '{"detail": "Phone number not found"}',
        )
        article = intel.db.query(HelpArticle).first()
        assert article.title is not None
        assert len(article.content) > 100
        assert "phone_number" in article.content

    def test_no_duplicate_articles(self, intel):
        intel.log_call("sim_swap", "/v1/sim-swap", "POST", "{}", 404, "not found")
        intel.log_call("sim_swap", "/v1/sim-swap", "POST", "{}", 404, "not found")
        articles = intel.db.query(HelpArticle).all()
        assert len(articles) == 1

    def test_articles_for_different_apis(self, intel):
        intel.log_call("sim_swap", "/v1/sim-swap", "POST", "{}", 404, "not found")
        intel.log_call("carrier_billing", "/v1/billing", "POST", "{}", 400, "missing field")
        articles = intel.db.query(HelpArticle).all()
        api_names = {a.api_name for a in articles}
        assert len(api_names) >= 2


# ── Help System ──

class TestHelpSystem:
    def test_get_api_help(self, intel):
        help_data = intel.get_api_help("sim_swap")
        assert help_data["api"] == "sim_swap"
        assert "reference" in help_data
        assert help_data["reference"]["endpoint"] == "/camara/v1/sim-swap/check"

    def test_get_api_help_includes_example(self, intel):
        help_data = intel.get_api_help("carrier_billing")
        assert "example" in help_data["reference"]
        assert "amount" in str(help_data["reference"]["example"])

    def test_get_api_help_invalid_raises(self, intel):
        with pytest.raises(HTTPException) as exc_info:
            intel.get_api_help("nonexistent_api")
        assert exc_info.value.status_code == 400

    def test_get_help_article_increments_views(self, intel):
        # First, generate an article
        intel.log_call("sim_swap", "/v1/sim-swap", "POST", "{}", 404, "not found")
        article = intel.db.query(HelpArticle).first()
        assert article is not None
        initial_views = article.views

        intel.get_help_article(article.id)
        assert article.views == initial_views + 1

    def test_get_help_article_not_found(self, intel):
        with pytest.raises(HTTPException):
            intel.get_help_article("nonexistent")

    def test_contextual_help(self, intel):
        intel.log_call("sim_swap", "/camara/v1/sim-swap/check", "POST", "{}", 404, "not found")
        results = intel.get_contextual_help("/camara/v1/sim-swap/check", error_code=404)
        assert isinstance(results, list)

    def test_contextual_help_unknown_endpoint(self, intel):
        results = intel.get_contextual_help("/unknown/endpoint")
        assert results == []


# ── Developer Analytics ──

class TestDeveloperAnalytics:
    def test_analytics_new_developer(self, intel, dev):
        analytics = intel.get_developer_analytics(dev.id)
        assert analytics["total_calls"] == 0
        assert analytics["developer"] == "Test Dev"

    def test_analytics_with_calls(self, intel, dev):
        intel.log_call("sim_swap", "/v1/sim-swap", "POST", "{}", 200, "{}", developer_id=dev.id)
        intel.log_call("sim_swap", "/v1/sim-swap", "POST", "{}", 404, "not found", developer_id=dev.id)
        intel.log_call("device_status", "/v1/device", "POST", "{}", 200, "{}", developer_id=dev.id)

        analytics = intel.get_developer_analytics(dev.id)
        assert analytics["total_calls"] == 3
        assert analytics["errors"] == 1
        assert analytics["success_rate"] == pytest.approx(2/3, abs=0.01)
        assert analytics["most_used_api"] == "sim_swap"

    def test_analytics_not_found(self, intel):
        with pytest.raises(HTTPException):
            intel.get_developer_analytics("nonexistent")


# ── Platform Analytics ──

class TestPlatformAnalytics:
    def test_empty_platform(self, intel):
        stats = intel.get_platform_analytics()
        assert stats["total_developers"] == 0
        assert stats["total_api_calls"] == 0

    def test_platform_with_activity(self, intel):
        dev = intel.register_developer("Alice", "Team A")
        intel.log_call("sim_swap", "/v1/sim-swap", "POST", "{}", 200, "{}", developer_id=dev.id)
        intel.log_call("sim_swap", "/v1/sim-swap", "POST", "{}", 404, "not found", developer_id=dev.id)
        intel.log_call("carrier_billing", "/v1/billing", "POST", "{}", 200, "{}", developer_id=dev.id)

        stats = intel.get_platform_analytics()
        assert stats["total_developers"] == 1
        assert stats["total_api_calls"] == 3
        assert stats["total_knowledge_gaps"] >= 1
        assert "sim_swap" in stats["api_popularity"]

    def test_coverage_per_api(self, intel):
        intel.log_call("sim_swap", "/v1/sim-swap", "POST", "{}", 404, "not found")
        stats = intel.get_platform_analytics()
        assert "sim_swap" in stats["knowledge_coverage"]
        assert stats["knowledge_coverage"]["sim_swap"]["gaps_found"] >= 1


# ── Manual Article Creation ──

class TestManualArticles:
    def test_create_manual_article(self, intel):
        article = intel.create_manual_article(
            "SIM Swap Best Practices",
            "Always check sim_swap_count alongside swapped flag...",
            "sim_swap",
            "workflow",
        )
        assert article.source == "manual"
        assert article.category == HelpCategory.WORKFLOW

    def test_vote_helpful(self, intel):
        article = intel.create_manual_article("Test", "Content", "sim_swap", "testing")
        result = intel.vote_helpful(article.id)
        assert result.helpful_votes == 1


# ── Integration: Full Developer Journey ──

class TestFullJourney:
    def test_developer_learns_from_failures(self, intel):
        """
        Full journey:
        1. Developer registers
        2. Makes mistakes (wrong format, wrong endpoint)
        3. System captures gaps and generates help
        4. Developer gets contextual help
        5. Makes correct calls
        6. Analytics show improvement
        """
        # 1. Register
        dev = intel.register_developer("Bob", "Carrier Integration")

        # 2. First attempt — wrong phone format
        intel.log_call("sim_swap", "/camara/v1/sim-swap/check", "POST",
                       '{"phone": "9876543210"}', 404,
                       '{"detail": "Phone number not found"}', 15.0, dev.id)

        # 3. System detected gap and generated help
        gaps = intel.db.query(KnowledgeGap).all()
        assert len(gaps) >= 1
        articles = intel.db.query(HelpArticle).all()
        assert len(articles) >= 1

        # 4. Developer reads help
        help_data = intel.get_api_help("sim_swap")
        assert help_data["reference"]["example"]["phone_number"].startswith("+")

        # 5. Correct call
        intel.log_call("sim_swap", "/camara/v1/sim-swap/check", "POST",
                       '{"phone_number": "+919876543210", "max_age_hours": 72}', 200,
                       '{"swapped": false, "sim_swap_count": 0}', 32.0, dev.id)

        # 6. Check analytics
        analytics = intel.get_developer_analytics(dev.id)
        assert analytics["total_calls"] == 2
        assert analytics["success_rate"] == 0.5  # 1 success, 1 failure

    def test_multiple_developers_share_knowledge(self, intel):
        """Knowledge from one developer helps another."""
        # Dev 1 makes a mistake
        dev1 = intel.register_developer("Alice", "Payments")
        intel.log_call("carrier_billing", "/camara/v1/carrier-billing/charge", "POST",
                       '{"phone": "9876543210"}', 404, '{"detail": "not found"}', 10.0, dev1.id)

        # Articles generated from dev 1's mistake
        articles = intel.db.query(HelpArticle).filter(HelpArticle.api_name == "carrier_billing").all()
        assert len(articles) >= 1

        # Dev 2 can access that knowledge
        dev2 = intel.register_developer("Bob", "Fraud")
        help_data = intel.get_api_help("carrier_billing")
        assert len(help_data["help_articles"]) >= 1

        # Platform shows collective intelligence
        stats = intel.get_platform_analytics()
        assert stats["total_developers"] == 2
        assert stats["total_knowledge_gaps"] >= 1
