# Implementation Plan: Maintenance Assistant Assessment

## Overview

Implementación del sistema de Assessment para el AI Maintenance Assistant (IA-SHEDULER-ZABBIX). El sistema se construye como una herramienta modular de análisis estático con analizadores independientes por dimensión (seguridad, bugs, duplicación, viabilidad nativa, consistencia, resiliencia, escalabilidad, UX, calidad de prompt), un motor de reglas configurable, parsing AST, y un generador de reportes consolidados con scoring y métricas.

La implementación sigue un enfoque incremental: primero la infraestructura base (modelos de datos, interfaces, configuración), luego los analizadores individuales, y finalmente la integración con el generador de reportes y el CLI.

## Tasks

- [x] 1. Set up project structure, data models, and core interfaces
  - [x] 1.1 Create project directory structure and configuration files
    - Create directory structure: `src/assessment/`, `src/assessment/analyzers/`, `src/assessment/core/`, `tests/unit/`, `tests/property/`, `tests/fixtures/`
    - Create `pyproject.toml` with dependencies: pytest, hypothesis, pytest-cov, ruff, mypy, pyyaml
    - Create `src/assessment/__init__.py` and sub-package init files
    - _Requirements: 10.1_

  - [x] 1.2 Implement data models and enums
    - Create `src/assessment/core/models.py` with all dataclasses: `Severity`, `Category`, `NativeViability`, `CodeLocation`, `Finding`, `DuplicationPair`, `ViabilityEntry`, `ViabilityMatrix`, `ExecutiveSummary`, `AssessmentReport`, `Rule`, `AssessmentConfig`, `ProjectContext`, `ExitCode`
    - Implement enum values as defined in design (Spanish labels for Severity and Category)
    - Implement computed properties on `ViabilityMatrix` (`native_viable_count`, `requires_backend_count`)
    - _Requirements: 10.1, 10.2, 4.5_

  - [x] 1.3 Implement BaseAnalyzer abstract class and AssessmentOrchestrator
    - Create `src/assessment/core/base_analyzer.py` with `BaseAnalyzer` ABC defining `category`, `analyze()`, and `get_rules()` abstract methods
    - Create `src/assessment/core/orchestrator.py` with `AssessmentOrchestrator` implementing `register_analyzer()`, `run()`, and `run_selective()`
    - Implement error handling: catch exceptions from individual analyzers, log errors, continue with remaining analyzers
    - _Requirements: 10.1, 10.5_

  - [x] 1.4 Implement Rule Engine and AST Parser utilities
    - Create `src/assessment/core/rule_engine.py` with `RuleEngine` class that loads rules from YAML/JSON and evaluates regex/AST patterns
    - Create `src/assessment/core/ast_parser.py` with utilities for parsing Python files (using `ast` module), JavaScript pattern matching (regex-based), and PHP pattern matching
    - Implement error handling: `SyntaxError` capture for invalid Python, fallback to regex for JS/PHP
    - _Requirements: 2.1, 3.1, 1.1_

- [x] 2. Implement Security and Bug Analyzers
  - [x] 2.1 Implement Security Analyzer
    - Create `src/assessment/analyzers/security_analyzer.py` implementing `SecurityAnalyzer`
    - Implement `check_cors_config()`: detect `CORS(app)` without origin restrictions, classify as high severity
    - Implement `check_auth_endpoints()`: identify Flask routes without authentication decorators, classify by risk level
    - Implement `check_rate_limiting()`: verify presence of rate limiting libraries/decorators
    - Implement `check_credentials_validation()`: detect env var usage without presence validation at startup
    - Implement `check_transport_security()`: detect token transmission without HTTPS enforcement
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [ ]* 2.2 Write property test for Security Analyzer endpoint classification
    - **Property 8: Security Endpoint Classification Completeness**
    - Generate random Flask AST trees with routes having/lacking auth decorators
    - Verify all unauthenticated endpoints are identified and classified into exactly one severity level
    - Verify no authenticated endpoint appears in results
    - **Validates: Requirements 1.1**

  - [x] 2.3 Implement Bug Analyzer
    - Create `src/assessment/analyzers/bug_analyzer.py` implementing `BugAnalyzer`
    - Implement `check_unhandled_exceptions()`: identify code paths where exceptions can cause HTTP 500
    - Implement `check_bitmask_validation()`: detect bitmask values sent to Zabbix API without range validation
    - Implement `check_race_conditions()`: detect concurrent request patterns in widget JS (double-click, multiple submits)
    - Implement `check_api_schema_validation()`: detect `_make_request` without response schema validation
    - Implement `check_timeout_retry()`: detect 30s timeout without retry mechanism
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ]* 2.4 Write unit tests for Security and Bug Analyzers
    - Test detection of `CORS(app)` without restrictions using sample Flask code fixture
    - Test detection of credentials without validation
    - Test detection of token without HTTPS
    - Test detection of missing rate limiting
    - Test detection of unhandled exceptions in route handlers
    - Test detection of bitmask values without validation
    - Test detection of timeout without retries
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 2.1, 2.4, 2.5_

- [x] 3. Implement Duplication and Consistency Analyzers
  - [x] 3.1 Implement Duplication Analyzer
    - Create `src/assessment/analyzers/duplication_analyzer.py` implementing `DuplicationAnalyzer`
    - Implement `compute_similarity()`: calculate similarity between code blocks (0.0-1.0) using token-based comparison
    - Implement `find_duplicates()`: find pairs of blocks with similarity above configurable threshold (default 70%)
    - Implement detection of ticket parsing duplication between prompt and `_extract_ticket_number`
    - Implement detection of cross-language duplication (Python `generate_maintenance_description` vs JS `formatRecurrenceConfig`)
    - Implement detection of repetitive patterns in recurrence type handling (daily, weekly, monthly)
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [ ]* 3.2 Write property test for Code Similarity Metric
    - **Property 1: Code Similarity Metric Invariants**
    - Generate random pairs of code block strings
    - Verify symmetry: `similarity(A, B) == similarity(B, A)`
    - Verify bounds: `0.0 <= similarity(A, B) <= 1.0`
    - Verify identity: `similarity(A, A) == 1.0`
    - Verify threshold filtering consistency
    - **Validates: Requirements 3.1**

  - [x] 3.3 Implement Consistency Analyzer
    - Create `src/assessment/analyzers/consistency_analyzer.py` implementing `ConsistencyAnalyzer`
    - Implement `extract_prompt_schema()`: parse AI prompt text to extract expected bitmask values, date formats, response types, and field optionality
    - Implement `extract_backend_schema()`: parse backend AST to extract processed bitmask values, date formats, handled response types, and field requirements
    - Implement `compare_schemas()`: compare prompt schema vs backend schema, report discrepancies
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ]* 3.4 Write property tests for Schema Comparison
    - **Property 2: Schema Comparison Detects All Value and Format Discrepancies**
    - Generate random dictionaries representing prompt and backend schemas
    - Verify every value in one schema but not the other is reported (no false negatives)
    - Verify consistent values are not reported (no false positives)
    - **Validates: Requirements 5.1, 5.2**

  - [ ]* 3.5 Write property test for Type and Optionality Mismatches
    - **Property 3: Schema Comparison Detects All Type and Optionality Mismatches**
    - Generate random sets of response types and boolean optionality flags
    - Verify symmetric difference is correctly identified
    - Verify optional/required mismatches are reported
    - **Validates: Requirements 5.3, 5.4**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement Native Viability, Resilience, and Scalability Analyzers
  - [x] 5.1 Implement Native Viability Analyzer
    - Create `src/assessment/analyzers/native_viability_analyzer.py` implementing `NativeViabilityAnalyzer`
    - Implement analysis of bitmask engine → classify as "nativa viable"
    - Implement analysis of ticket validation (pattern XXX-XXXXXX) → classify as "nativa viable"
    - Implement analysis of date/time parsing → classify as "nativa parcial"
    - Implement analysis of host/group search → classify as "requiere backend obligatoriamente"
    - Implement `generate_viability_matrix()`: produce complete `ViabilityMatrix` with all entries classified
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 5.2 Write property test for Viability Matrix Categorization
    - **Property 4: Viability Matrix Categorization Consistency**
    - Generate random lists of `ViabilityEntry` objects with random classifications
    - Verify entries are partitioned into exactly three categories
    - Verify sum of entries across categories equals total input entries (no loss or duplication)
    - **Validates: Requirements 4.5**

  - [x] 5.3 Implement Resilience Analyzer
    - Create `src/assessment/analyzers/resilience_analyzer.py` implementing `ResilienceAnalyzer`
    - Implement evaluation of graceful degradation when Zabbix API is unavailable
    - Implement evaluation of fallback behavior when AI Provider fails
    - Implement evaluation of widget retry mechanism (max_retries=2) and timeouts (60s request, 10s health)
    - Implement evaluation of connection loss handling during maintenance confirmation
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [x] 5.4 Implement Scalability Analyzer
    - Create `src/assessment/analyzers/scalability_analyzer.py` implementing `ScalabilityAnalyzer`
    - Implement Docker Compose port conflict detection across service definitions
    - Implement shared state collision risk analysis between instances
    - Implement subnet capacity evaluation (172.31.10.0/24 for max planned instances)
    - Implement resource consumption estimation for 5+ concurrent instances with active AI providers
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ]* 5.5 Write property test for Docker Port Conflict Detection
    - **Property 9: Docker Port Conflict Detection**
    - Generate random Docker Compose configurations with multiple services and port mappings
    - Verify all port conflicts are detected (same host port on different services)
    - Verify no false positives for non-conflicting configurations
    - **Validates: Requirements 7.1**

- [x] 6. Implement UX and Prompt Quality Analyzers
  - [x] 6.1 Implement UX Analyzer
    - Create `src/assessment/analyzers/ux_analyzer.py` implementing `UXAnalyzer`
    - Implement evaluation of onboarding flow (welcome message, examples sufficiency)
    - Implement verification that all error messages are in Spanish and comprehensible for non-technical staff
    - Implement evaluation of confirmation flow clarity (information presented before confirm)
    - Implement evaluation of visual feedback during long operations (loading states, progress indicators)
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 6.2 Implement Prompt Quality Analyzer
    - Create `src/assessment/analyzers/prompt_quality_analyzer.py` implementing `PromptQualityAnalyzer`
    - Implement detection of ambiguities that may cause inconsistent responses between Gemini and OpenAI
    - Implement evaluation of example coverage for common operations team use cases
    - Implement identification of uncovered edge cases (past dates, invalid bitmasks, non-existent hosts)
    - Implement token efficiency analysis (prompt size optimization opportunities)
    - Implement detection of missing instructions for handling ambiguous user requests
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ]* 6.3 Write unit tests for UX and Prompt Quality Analyzers
    - Test onboarding message evaluation with sample widget code
    - Test Spanish language verification in error messages
    - Test prompt ambiguity detection with sample prompts
    - Test edge case identification in prompt examples
    - Test token count estimation
    - _Requirements: 8.1, 8.2, 9.1, 9.3, 9.4_

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement Report Generator and CLI
  - [x] 8.1 Implement Report Generator
    - Create `src/assessment/core/report_generator.py` implementing `ReportGenerator`
    - Implement `classify_findings()`: group findings by category and severity
    - Implement `compute_risk_score()`: calculate risk score (1-10) based on findings distribution
    - Implement `identify_quick_wins()`: filter findings where `effort_hours < 2.0` AND severity is CRITICAL or HIGH
    - Implement `generate_executive_summary()`: compute total findings, findings by category/severity, risk score, technical debt hours, quick wins count, critical issues count
    - Implement `export_markdown()`: generate Markdown report with all sections
    - Implement `export_json()`: generate structured JSON report
    - Include viability matrix section in report output
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [ ]* 8.2 Write property test for Report Preserves All Findings
    - **Property 5: Report Preserves All Findings with Correct Classification**
    - Generate random lists of `Finding` objects with valid categories and severities
    - Verify every input finding appears exactly once in the report
    - Verify findings are grouped under correct category and severity
    - Verify all findings have non-empty description, location, impact, and recommendation
    - **Validates: Requirements 10.1, 10.2**

  - [ ]* 8.3 Write property test for Quick Wins Filtering
    - **Property 6: Quick Wins Filtering Correctness**
    - Generate random lists of `Finding` with varying `effort_hours` and severity
    - Verify quick wins contains exactly findings where `effort_hours < 2.0` AND severity is CRITICAL or HIGH
    - Verify no findings outside criteria appear in quick wins
    - **Validates: Requirements 10.3**

  - [ ]* 8.4 Write property test for Executive Summary Metrics
    - **Property 7: Executive Summary Metrics Consistency**
    - Generate random sets of findings with categories and severities
    - Verify `total_findings` equals count of all findings
    - Verify sum of `findings_by_category` equals `total_findings`
    - Verify sum of `findings_by_severity` equals `total_findings`
    - Verify `risk_score` is in range [1, 10]
    - Verify `technical_debt_hours` equals sum of all findings' `effort_hours`
    - **Validates: Requirements 10.5**

  - [x] 8.5 Implement CLI Entry Point
    - Create `src/assessment/cli.py` with CLI using argparse or click
    - Implement commands: `assess` (full assessment), `assess --categories security,bug` (selective)
    - Implement output options: `--format markdown|json|both`, `--output <path>`
    - Implement exit codes as defined in `ExitCode` enum
    - Wire CLI to `AssessmentOrchestrator` with all analyzers registered
    - _Requirements: 10.1, 10.5_

- [x] 9. Integration, wiring, and test fixtures
  - [x] 9.1 Create test fixtures for sample project code
    - Create `tests/fixtures/sample_flask_app.py`: sample Flask app with known security issues (CORS, no auth, no rate limiting)
    - Create `tests/fixtures/sample_widget.js`: sample widget JS with known patterns (race conditions, missing feedback)
    - Create `tests/fixtures/sample_docker_compose.yml`: sample Docker Compose with port conflicts and subnet config
    - Create `tests/fixtures/sample_prompt.txt`: sample AI prompt with known ambiguities and edge case gaps
    - _Requirements: 1.1, 2.3, 7.1, 9.1_

  - [x] 9.2 Wire all analyzers into Orchestrator and validate end-to-end flow
    - Register all 9 analyzers in the orchestrator
    - Run full assessment against test fixtures
    - Verify report contains findings from all categories
    - Verify viability matrix is included in final report
    - Verify executive summary metrics are consistent
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [ ]* 9.3 Write integration tests for end-to-end assessment flow
    - Test full assessment run against fixtures produces valid report
    - Test selective assessment (single category) produces filtered results
    - Test CLI invocation with different output formats
    - Test error handling when project path doesn't exist
    - _Requirements: 10.1, 10.5_

- [ ] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties defined in the design document
- Unit tests validate specific examples and edge cases
- The implementation language is Python as specified in the design document
- Testing uses pytest + Hypothesis for property-based tests
- All analyzers follow the `BaseAnalyzer` interface for consistency and extensibility

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "1.4"] },
    { "id": 3, "tasks": ["2.1", "2.3", "3.1", "3.3"] },
    { "id": 4, "tasks": ["2.2", "2.4", "3.2", "3.4", "3.5"] },
    { "id": 5, "tasks": ["5.1", "5.3", "5.4", "6.1", "6.2"] },
    { "id": 6, "tasks": ["5.2", "5.5", "6.3"] },
    { "id": 7, "tasks": ["8.1", "9.1"] },
    { "id": 8, "tasks": ["8.2", "8.3", "8.4", "8.5"] },
    { "id": 9, "tasks": ["9.2"] },
    { "id": 10, "tasks": ["9.3"] }
  ]
}
```
