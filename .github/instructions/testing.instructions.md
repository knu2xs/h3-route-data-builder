---
applyTo: "testing/**/*.py"
---

<!-- Generated from AGENTS.md by post_gen_project.py — do not edit directly. -->

The project uses **PyTest** as the testing framework. Follow PyTest conventions when writing and
organizing tests. Run the full test suite at any time with `make test`.

#### 8.1 File and Module Organization

- Mirror the `src/h3_route_data_builder/` package structure in `testing/`:
    - One test file per module: `testing/test_<module_name>.py`
    - Example: `src/h3_route_data_builder/analysis.py` → `testing/test_analysis.py`
- Use `testing/test_h3_route_data_builder.py` for package-level smoke tests
- Do not place test files inside `src/`

#### 8.2 Naming Conventions

- **Test files**: `test_*.py`
- **Test functions**: `test_<what_is_being_tested>()` — names should read like a sentence
    - Good: `test_buffer_returns_expected_area()`
    - Avoid: `test1()`, `test_thing()`
- **Test classes** (when grouping related tests): `Test<ClassName>` with no `__init__`
- **Fixtures**: descriptive lowercase names (e.g., `temp_gdb`, `sample_feature_class`)

#### 8.3 Fixtures

- Place **reusable fixtures** in `testing/conftest.py` — PyTest discovers them automatically for
  all test files without explicit imports
- The following fixtures are pre-defined in `conftest.py`:
    - `temp_dir` — provides a temporary `Path` directory; deleted after each test
    - `temp_gdb` — provides a temporary ArcGIS file geodatabase `Path`; deleted after each test
    - `setup_environment` — session-scoped; sets `TEST_ENV=true` for the full test session
- Use the **narrowest scope possible**: prefer `scope="function"` (default) unless the setup cost
  justifies `scope="module"` or `scope="session"`
- Parametrize repetitive test cases with `@pytest.mark.parametrize` rather than writing duplicate
  test functions

#### 8.4 Test Writing Guidelines

- Each test must be **independent and isolated** — tests must not depend on execution order or
  shared mutable state
- Use plain `assert` statements; PyTest rewrites them to provide detailed failure output
- Test **one behavior per function**; keep tests small and focused
- Avoid testing third-party libraries (arcpy, pandas, etc.) — only test project code
- For ArcPy-dependent tests, use the `temp_gdb` fixture for all intermediate and output data
- Mock external calls and expensive operations using `unittest.mock` or `pytest-mock`
- Prefer `monkeypatch` over module-level patching to keep side-effects scoped to the test
- Do not use `print()` in tests; use `pytest`'s captured output or logging assertions instead

#### 8.5 Running Tests

- Run all tests: `make test`
- Run a single file: `pytest testing/test_<module>.py`
- Run a single test by name: `pytest testing/test_<module>.py::test_function_name`
- Run with verbose output: `pytest -v`
- Run with coverage (if `pytest-cov` is installed):
  `pytest --cov=h3_route_data_builder --cov-report=term-missing`
