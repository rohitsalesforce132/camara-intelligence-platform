# Contributing to CAMARA Developer Intelligence Platform

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

---

## 🤝 How to Contribute

### Reporting Bugs

Before creating bug reports, please check the existing issues to avoid duplicates. When creating a bug report, include:

- **Clear description** of the problem
- **Steps to reproduce** the issue
- **Expected behavior** vs **actual behavior**
- **Environment details:** OS, Python version, installed dependencies
- **Logs/error messages** (if applicable)

### Suggesting Enhancements

Enhancement suggestions are welcome! Please include:

- **Clear description** of the proposed enhancement
- **Motivation:** Why would this enhancement be useful?
- **Use cases:** How would you use this feature?
- **Alternatives considered:** What other approaches did you consider?

### Pull Requests

1. **Fork the repository** and create your branch from `main`
2. **Make your changes** following the code style guidelines
3. **Add tests** for new functionality (aim for >90% coverage)
4. **Update documentation** (README, ARCHITECTURE.md, etc.)
5. **Run tests** and ensure all pass: `pytest`
6. **Commit your changes** with clear, descriptive messages
7. **Push to your fork** and submit a pull request

---

## 🛠️ Development Setup

### 1. Clone and Install

```bash
git clone https://github.com/rohitsalesforce132/camara-intelligence-platform.git
cd camara-intelligence-platform
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install pytest pytest-cov  # For testing
```

### 2. Run the Platform

```bash
uvicorn camara_intelligence.platform:app --reload --port 8093
```

Visit `http://localhost:8093/docs` for interactive API documentation.

### 3. Run Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=camara_intelligence --cov-report=html

# Run specific test
pytest tests/test_platform.py::TestGapDetection::test_404_creates_gap
```

### 4. Code Style

We follow PEP 8 style guidelines. Use `black` for formatting:

```bash
pip install black
black camara_intelligence/ tests/
```

---

## 📁 Project Structure

```
camara-intelligence-platform/
├── camara_intelligence/
│   ├── __init__.py              # Package initialization
│   └── platform.py              # Core platform (FastAPI + Engine)
├── tests/
│   ├── __init__.py
│   └── test_platform.py         # Test suite
├── requirements.txt             # Dependencies
├── README.md                    # Project overview
├── STAR.md                      # STAR method interview prep
├── ARCHITECTURE.md              # Detailed architecture
├── STAR-TEMPLATE.md             # STAR template reference
└── CONTRIBUTING.md              # This file
```

---

## 🧪 Testing Guidelines

### Test Coverage Goal: >90%

Currently: **92%** (26 tests, all passing)

### Writing Tests

1. **Use fixtures** for shared setup (see `conftest.py` if needed)
2. **Test one thing** per test function
3. **Use descriptive names** (e.g., `test_404_creates_gap`)
4. **Test both happy path** and edge cases
5. **Test database operations** (CRUD) thoroughly

### Test Categories

- **Unit tests:** Individual functions/methods
- **Integration tests:** Multiple components working together
- **End-to-end tests:** Full user journeys (see `TestFullJourney`)

### Example Test

```python
def test_gap_detection_on_404(intel):
    """Test that a 404 response creates a knowledge gap."""
    intel.log_call(
        "sim_swap",
        "/camara/v1/sim-swap/check",
        "POST",
        '{"phone": "bad"}',
        404,
        '{"detail": "Phone number not found"}',
    )

    gaps = intel.db.query(KnowledgeGap).all()
    assert len(gaps) == 1
    assert gaps[0].gap_type == GapType.WRONG_FORMAT
```

---

## 📝 Documentation Guidelines

### README.md

- **Keep it up-to-date** with the latest features
- **Include quick start** instructions
- **Add usage examples** for all major features
- **Document API endpoints** (or link to `/docs`)

### ARCHITECTURE.md

- **Update diagrams** when architecture changes
- **Document design decisions** and trade-offs
- **Include data flow** for new features
- **Update scalability** considerations if needed

### Code Comments

- **Docstrings** for all public functions/classes (Google style)
- **Inline comments** for complex logic only
- **Avoid obvious comments** (e.g., `# increment counter`)

```python
def detect_gap(self, call: ApiCall) -> KnowledgeGap | None:
    """
    Analyze a failed API call and create/update a knowledge gap.

    Matches the call against ERROR_PATTERNS to identify the gap type.
    If an identical gap exists, increments its frequency instead of creating
    a new one.

    Args:
        call: The failed API call to analyze.

    Returns:
        The new or updated KnowledgeGap, or None if no gap detected.
    """
    # Implementation...
```

---

## 🎯 Feature Development Guidelines

### Before Starting

1. **Check existing issues** and pull requests
2. **Create an issue** to discuss the feature (if it doesn't exist)
3. **Get feedback** from maintainers before starting work
4. **Design the solution** (data models, APIs, tests)

### During Development

1. **Work in a feature branch:** `git checkout -b feature/your-feature-name`
2. **Commit frequently** with clear messages
3. **Test as you go** — don't leave testing for the end
4. **Update documentation** alongside code changes

### Before Submitting PR

1. **Rebase** your branch on the latest `main`
2. **Run full test suite:** `pytest --cov=camara_intelligence`
3. **Check code style:** `black camara_intelligence/ tests/`
4. **Review your own changes** — is it ready for merge?
5. **Update PR description** with:
   - What changed
   - Why it matters
   - How to test
   - Related issues

---

## 🐛 Bug Fix Guidelines

### Before Fixing

1. **Reproduce the bug** locally
2. **Add a failing test** that captures the bug
3. **Verify the test fails** before the fix

### After Fixing

1. **Verify the test passes** after the fix
2. **Check for regressions** — run full test suite
3. **Add documentation** if the bug revealed unclear behavior

---

## 📊 Release Process

### Versioning

We follow [Semantic Versioning](https://semver.org/):
- **MAJOR:** Breaking changes
- **MINOR:** New features (backwards compatible)
- **PATCH:** Bug fixes (backwards compatible)

### Release Checklist

- [ ] All tests passing
- [ ] Documentation updated
- [ ] Changelog updated (CHANGELOG.md)
- [ ] Version bumped in `camara_intelligence/__init__.py`
- [ ] Git tag created: `git tag -a v1.0.0 -m "Release v1.0.0"`
- [ ] Tag pushed: `git push origin v1.0.0`

---

## 📜 Code of Conduct

### Be Respectful

- **Treat everyone** with respect and professionalism
- **Welcome newcomers** and help them learn
- **Focus on what is best** for the community
- **Show empathy** toward other community members

### Unacceptable Behavior

- Harassment, trolling, or discriminatory language
- Personal attacks or insulting comments
- Private or public harassment
- Publishing others' private information
- Other unethical or unprofessional conduct

### Reporting Issues

If you encounter unacceptable behavior, please contact the project maintainers directly.

---

## 🤖 GitHub Copilot Integration

This project includes `.github/copilot-instructions.md` to help GitHub Copilot understand the codebase and generate better suggestions.

### When Copilot is Helpful

- **Boilerplate code:** Pydantic models, SQLAlchemy models, FastAPI endpoints
- **Test scaffolding:** Given a function, generate test cases
- **Documentation:** Generate docstrings from code

### When to Trust Copilot

- **Simple patterns** that match existing code style
- **Well-understood domains** (e.g., standard FastAPI patterns)
- **Repetitive code** where you provide clear context

### When to Be Careful

- **Complex business logic** — review carefully
- **Database queries** — check for N+1 issues
- **Security-sensitive code** — never trust blindly

---

## 💬 Getting Help

- **GitHub Issues:** For bugs, feature requests, questions
- **Discussions:** For general questions and ideas
- **Email:** rohitsalesforce132@gmail.com

---

## 📄 License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

**Thank you for contributing! 🎉**
