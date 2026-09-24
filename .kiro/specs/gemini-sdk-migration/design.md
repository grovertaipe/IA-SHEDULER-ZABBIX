# Gemini SDK Migration Bugfix Design

## Overview

The Gemini provider (`backend/ai/gemini_provider.py`) wraps the deprecated
`google-generativeai==0.7.2` SDK. That SDK cannot be imported on Python 3.14 — it raises
`Metaclasses with custom tp_new are not supported` at import time. Because the provider
imports the SDK lazily and swallows import failures (to degrade gracefully), the net effect
on Python 3.14 is that `GeminiProvider.is_available()` returns `False` for every request,
so `/chat` and `/parse` always answer "El asistente de IA no está disponible".

The fix migrates the provider to the official **`google-genai`** SDK (Google Gen AI SDK),
which supports Python 3.14. The migration is intentionally minimal and surgical: the
public `GeminiProvider` contract, the lazy-import pattern, the logging behavior, the prompt
building, the response parsing, and the generation parameters are all preserved. Only the
SDK import, client construction, and the single `generate_content` call change. The new SDK
is stateless per request (the client holds only auth; the model name is passed per call), so
`is_available()` checks that an API key is set and the client object was constructed.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — running on Python 3.14 while
  constructing/using `GeminiProvider` with a valid API key, where the legacy
  `google-generativeai` SDK import fails and leaves the provider unavailable.
- **Property (P)**: The desired behavior — with a valid API key and the `google-genai` SDK
  installed, the client is constructed, `is_available()` returns `True`, and `extract()`
  runs AI extraction and returns a parsed `ExtractedRequest`.
- **Preservation**: The unavailable-without-key path, the no-SDK-installed lazy-import path,
  the public interface, the prompt/parse behavior, the fixed generation parameters, and the
  entire OpenAI provider — all must remain unchanged by the fix.
- **GeminiProvider**: The class in `backend/ai/gemini_provider.py` implementing the
  `AIProvider` interface: `__init__(api_key: str | None, model: str)`, `is_available() -> bool`,
  and `extract(message: str, ctx: PromptContext) -> ExtractedRequest`.
- **google-genai**: The new official Google Gen AI SDK (`from google import genai`,
  `from google.genai import types`), which supports Python 3.14.
- **google-generativeai**: The deprecated SDK (`import google.generativeai as genai`) that
  fails to import on Python 3.14.
- **is_available()**: Returns whether the provider is configured and usable — after the fix,
  `api_key is not None AND client is not None`.

## Bug Details

### Bug Condition

The bug manifests whenever `GeminiProvider` is constructed with a valid API key while the
process runs on Python 3.14. The lazy `import google.generativeai` inside the constructor
raises `Metaclasses with custom tp_new are not supported`; the constructor's broad
`except Exception` logs the failure and leaves `self._model = None`, so the provider reports
itself unavailable and `extract()` is never able to call the model.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type ProviderConstruction
         (fields: python_version, api_key, sdk = "google-generativeai")
  OUTPUT: boolean

  RETURN input.api_key IS NOT EMPTY
         AND legacyImportFails(input.python_version)   // true on Python 3.14
         AND resultingProviderIsAvailable(input) = FALSE  // expected TRUE
END FUNCTION
```

### Examples

- On Python 3.14 with `GOOGLE_API_KEY` set: `GeminiProvider(key, "gemini-2.0-flash").is_available()`
  returns `False` (expected: `True`). The logs show
  `google-generativeai is not available: Metaclasses with custom tp_new are not supported`.
- A `/parse` request with a valid key returns "El asistente de IA no está disponible"
  (expected: a parsed `ExtractedRequest`).
- A `/chat` request with a valid key returns the unavailability message (expected: AI runs).
- Edge case (no key): `GeminiProvider(None, "gemini-2.0-flash").is_available()` returns
  `False` — this is correct and must remain unchanged.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- The public interface of `GeminiProvider` stays identical: constructor `(api_key, model)`,
  `is_available() -> bool`, `extract(message, ctx) -> ExtractedRequest`.
- The lazy-import pattern stays: importing the module never hard-fails when the SDK is
  missing; only constructing/using the provider requires it.
- Missing API key → logs the reason (never the secret) and `is_available()` returns `False`;
  `extract()` raises `AIProviderError`.
- Missing SDK → module import still succeeds; `is_available()` returns `False`; `extract()`
  raises `AIProviderError`.
- Prompt building via `_build_prompt` / `_fallback_prompt` is unchanged; response parsing via
  `parse_response_text(text, message)` is unchanged; no bitmask arithmetic is performed.
- Generation parameters stay fixed: `_TEMPERATURE = 0.2`, `_MAX_OUTPUT_TOKENS = 1200`.
- The OpenAI provider (`backend/ai/openai_provider.py`) is not modified at all.

**Scope:**
All inputs that do NOT involve constructing/using the Gemini provider with a valid key on a
supported runtime should be completely unaffected. This includes:
- Construction without an API key.
- Environments where no AI SDK is installed.
- The OpenAI provider and the failover/factory orchestration.

## Hypothesized Root Cause

1. **Deprecated SDK incompatible with Python 3.14**: `google-generativeai==0.7.2` defines
   metaclasses with a custom `tp_new`, which Python 3.14 no longer supports; the import
   raises before any client can be built.

2. **Graceful degradation masks the failure**: the constructor catches the import error and
   only logs it, leaving `self._model = None`. There is no crash, so the symptom surfaces
   downstream as a persistent "unavailable" state rather than an obvious error.

3. **API surface mismatch**: even if imported, the legacy call shape
   (`genai.configure(...)` + `GenerativeModel(...).generate_content(...,
   generation_config={...})`) differs from the new SDK
   (`genai.Client(api_key=...)` + `client.models.generate_content(model=..., contents=...,
   config=types.GenerateContentConfig(...))`), so the fix must also adapt the call.

## Correctness Properties

Property 1: Bug Condition - Gemini Provider Available After SDK Migration

_For any_ construction where the bug condition holds (a valid API key is present and the
`google-genai` SDK is importable on the running interpreter, i.e. `isBugCondition` would have
been true under the legacy SDK), the fixed `GeminiProvider` SHALL import `google-genai`,
construct a client, and return `is_available() == True`; and a subsequent `extract()` with a
stubbed SDK response SHALL return the `ExtractedRequest` produced by `parse_response_text`.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - Non-Bug Inputs Behave Identically

_For any_ input where the bug condition does NOT hold — no API key, or the SDK not installed —
the fixed `GeminiProvider` SHALL produce the same observable result as the original: module
import never hard-fails, `is_available()` returns `False`, `extract()` raises `AIProviderError`,
the missing reason is logged without secrets, and the OpenAI provider plus the fixed generation
parameters (temperature 0.2, max output tokens 1200) and prompt/parse delegation are unchanged.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

## Fix Implementation

### Changes Required

**File**: `backend/ai/gemini_provider.py`

**Function**: `GeminiProvider.__init__` and `GeminiProvider.extract` (plus the module docstring)

**Specific Changes**:
1. **Module docstring**: reference `google-genai` (Google Gen AI SDK) instead of
   `google-generativeai`; keep the lazy-import note and requirement references.

2. **Lazy import (constructor)**: replace `import google.generativeai as genai` with
   `from google import genai` and `from google.genai import types`, inside the same
   try/except that logs failures. Update the failure log to name `google-genai` while never
   logging the key.

3. **Client construction (constructor)**: replace
   `genai.configure(api_key=...)` + `self._model = genai.GenerativeModel(self._model_name)`
   with `self._client = genai.Client(api_key=self._api_key)`. Store the client and keep the
   model name in `self._model_name`. Keep the info log
   `"Gemini provider configured (model=%s)"`.

4. **State fields**: rename the stored SDK handle from `self._model` to `self._client` (the
   new SDK is stateless per request; the client holds only auth) and store `types` if needed
   for the config object. `is_available()` becomes
   `self._api_key is not None and self._client is not None`.

5. **Request call (`extract`)**: replace
   `self._model.generate_content(prompt, generation_config={...})`
   with
   `self._client.models.generate_content(model=self._model_name, contents=prompt,
   config=types.GenerateContentConfig(temperature=_TEMPERATURE,
   max_output_tokens=_MAX_OUTPUT_TOKENS))`.
   Keep the surrounding `try/except` mapping SDK errors to `AIProviderError`, keep
   `text = getattr(response, "text", "") or ""`, and keep `return parse_response_text(text, message)`.

**File**: `backend/requirements.txt`
- Remove `google-generativeai==0.7.2`.
- Add `google-genai==1.31.0` (current stable 1.x confirmed to declare Python 3.14 support).
- Keep every other dependency unchanged.

**Files**: `backend/.env.example`, `backend/README.md`
- Update ONLY if they name the SDK. (Investigation found no reference to the SDK name or to
  `GOOGLE_API_KEY` in either file, so no change is expected. The env var name stays
  `GOOGLE_API_KEY`.)

**File**: `backend/ai/openai_provider.py`
- No change. Verified separate from the Gemini provider.

## Testing Strategy

### Validation Approach

Two phases: first surface counterexamples that demonstrate the bug on the unfixed code, then
verify the fix works and preserves existing behavior. Tests must NOT make live Gemini API
calls; the SDK client and its `generate_content` are stubbed/monkeypatched.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix and
confirm the root cause (SDK import failure / API-surface mismatch), not a network issue.

**Test Plan**: Because the actual failure is Python-3.14-specific and environment-bound, scope
the exploratory property to the concrete deterministic failing case: construct
`GeminiProvider` with a dummy-but-nonempty key on the running interpreter and assert the fixed
behavior (`is_available()` is `True` and the client was built without the metaclass error).
Run this against the UNFIXED code to observe the failure.

**Test Cases**:
1. **Availability with key (import path)**: `GeminiProvider("dummy-key", "gemini-2.0-flash").is_available()`
   is expected to be `True`. On UNFIXED code + Python 3.14 this FAILS (client never built).
2. **Import smoke**: `from google import genai` succeeds on the interpreter. On the unfixed
   environment the legacy `import google.generativeai` path is what fails.
3. **Extract returns parsed request (stubbed SDK)**: with the client's
   `models.generate_content` monkeypatched to return an object whose `.text` is a JSON blob,
   `extract()` returns the `ExtractedRequest` from `parse_response_text`. On UNFIXED code the
   provider is unavailable, so `extract()` raises instead.

**Expected Counterexamples**:
- `is_available()` returns `False` despite a valid key.
- Logs contain `google-generativeai is not available: Metaclasses with custom tp_new are not supported`.

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function
produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  provider := GeminiProvider_fixed(input.api_key, input.model)
  ASSERT provider.is_available() = TRUE
  // with a stubbed SDK response:
  ASSERT provider.extract(msg, ctx) = parse_response_text(stubbed_text, msg)
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function
produces the same result as the original.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT GeminiProvider_original(input) = GeminiProvider_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation because it
generates many non-buggy inputs (varied model names, empty/None keys) across the input domain
and provides stronger guarantees that behavior is unchanged.

**Test Plan**: Observe behavior on UNFIXED code for the no-key and no-SDK cases, then write
property-based tests capturing that behavior.

**Test Cases**:
1. **No-key unavailability**: for any model name, `GeminiProvider(None, model).is_available()`
   is `False` and `extract()` raises `AIProviderError` — unchanged after the fix.
2. **Missing-SDK lazy import**: with the `google` import forced to fail, importing the module
   still succeeds and the provider is unavailable — unchanged after the fix.
3. **Generation parameters constant**: `_TEMPERATURE == 0.2` and `_MAX_OUTPUT_TOKENS == 1200`
   — unchanged after the fix.
4. **OpenAI provider untouched**: OpenAI provider construction/availability behavior is
   unchanged (no edits to that module).
5. **Factory/failover contract**: `factory.build_provider(cfg_with_gemini)` still returns a
   `FailoverAIProvider`, and with no key it is unavailable — unchanged after the fix.

### Unit Tests

- `GeminiProvider` availability with a dummy key (client built) vs. without a key.
- `extract()` with a monkeypatched `client.models.generate_content` returning a `.text` JSON
  blob → asserts the parsed `ExtractedRequest` and that no network call is made.
- `extract()` maps SDK exceptions to `AIProviderError`.
- Generation parameters and delegation to `parse_response_text` are exercised.

### Property-Based Tests

- Preservation: for arbitrary model-name strings and empty/None keys, availability is `False`
  and `extract()` raises `AIProviderError`.
- Bug condition (scoped): for a nonempty key, availability is `True` on the running
  interpreter after the fix.

### Integration Tests

- Existing failover/factory tests (`tests/unit/test_failover_provider.py`) continue to pass
  unchanged, confirming the `GeminiProvider` contract still satisfies the factory and failover
  layers.
- Full suite (`pytest -q`) stays green (~45 tests), and `ruff`/`mypy` stay clean.
