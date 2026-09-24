# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Gemini Provider Available After SDK Migration
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists on Python 3.14
  - **Scoped PBT Approach**: The failure is deterministic per interpreter, so scope the property to the concrete failing case: construct `GeminiProvider("dummy-key", "gemini-2.0-flash")` and assert `is_available() is True` (from Bug Condition in design)
  - Add a stubbed-SDK case: monkeypatch the client's `models.generate_content` to return an object whose `.text` is a JSON blob, then assert `extract(message, ctx)` equals `parse_response_text(stubbed_text, message)` — NEVER make a live Gemini API call
  - The test assertions must match the Expected Behavior Properties from design (Property 1)
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (proves the bug: `is_available()` is `False` and logs show "google-generativeai is not available: Metaclasses with custom tp_new are not supported")
  - Document counterexamples found to understand root cause
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-Bug Inputs Behave Identically
  - **IMPORTANT**: Follow observation-first methodology — observe behavior on UNFIXED code first
  - Observe: `GeminiProvider(None, "gemini-2.0-flash").is_available()` is `False` and `extract(...)` raises `AIProviderError` on unfixed code
  - Observe: importing `backend/ai/gemini_provider.py` succeeds even when the AI SDK import is forced to fail (lazy import)
  - Observe: `_TEMPERATURE == 0.2` and `_MAX_OUTPUT_TOKENS == 1200`
  - Write property-based tests capturing observed behavior from the Preservation Requirements (for arbitrary model-name strings and empty/None keys, availability is `False` and `extract()` raises `AIProviderError`)
  - Include a check that the OpenAI provider and `factory.build_provider(cfg_with_gemini)` behavior are unchanged (returns `FailoverAIProvider`; unavailable with no key)
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Fix Gemini SDK incompatibility on Python 3.14 (migrate to google-genai)

  - [x] 3.1 Migrate `gemini_provider.py` to the `google-genai` SDK
    - Update the module docstring to reference `google-genai` (Google Gen AI SDK) instead of `google-generativeai`; keep the lazy-import note
    - In `__init__`, replace the lazy `import google.generativeai as genai` with `from google import genai` and `from google.genai import types`, inside the existing try/except that logs failures (log the failure reason for `google-genai`, never the key)
    - Replace `genai.configure(...)` + `GenerativeModel(...)` with `self._client = genai.Client(api_key=self._api_key)`; store the client (rename `self._model` → `self._client`) and keep `self._model_name`; keep the info log `"Gemini provider configured (model=%s)"`
    - Update `is_available()` to `return self._api_key is not None and self._client is not None`
    - In `extract`, call `self._client.models.generate_content(model=self._model_name, contents=prompt, config=types.GenerateContentConfig(temperature=_TEMPERATURE, max_output_tokens=_MAX_OUTPUT_TOKENS))`; keep the try/except → `AIProviderError`, keep `text = getattr(response, "text", "") or ""`, keep `return parse_response_text(text, message)`
    - Update `backend/requirements.txt`: remove `google-generativeai==0.7.2`, add `google-genai==1.31.0`, keep all other deps
    - Update `backend/.env.example` and `backend/README.md` ONLY if they name the SDK (investigation found no reference; env var `GOOGLE_API_KEY` stays)
    - Do NOT modify `backend/ai/openai_provider.py`
    - Install into the venv: `backend\.venv\Scripts\python.exe -m pip install google-genai==1.31.0`, then `-m pip uninstall -y google-generativeai`
    - _Bug_Condition: isBugCondition(input) from design (valid key + legacy import fails on Python 3.14)_
    - _Expected_Behavior: expectedBehavior(result) from design (client built, is_available True, extract returns parsed request)_
    - _Preservation: Preservation Requirements from design (no-key path, no-SDK path, public interface, prompt/parse, params, OpenAI untouched)_
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Gemini Provider Available After SDK Migration
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - Also run the direct import check: `.\.venv\Scripts\python.exe -c "from google import genai; print('google-genai import OK')"`
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed — `is_available()` is `True` with a key; `extract()` returns the stubbed parsed request)
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-Bug Inputs Behave Identically
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions in no-key/no-SDK paths, params, OpenAI, and factory/failover)
    - Confirm all tests still pass after fix (no regressions)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 4. Checkpoint - Ensure all tests pass
  - Run from `backend/` using the venv python:
    - `.\.venv\Scripts\python.exe -m ruff check .` → must stay clean
    - `.\.venv\Scripts\python.exe -m mypy` → must stay clean (config-driven, no args)
    - `.\.venv\Scripts\python.exe -m pytest -q` → all existing tests pass (~45); if a test patches `google.generativeai`, update it to patch the new SDK import path while keeping the test's intent
  - Ensure all tests pass, ask the user if questions arise
