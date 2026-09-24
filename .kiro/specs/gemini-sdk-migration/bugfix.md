# Bugfix Requirements Document

## Introduction

The `zabbix-ai-maintenance-v2` backend uses the deprecated `google-generativeai==0.7.2`
SDK in `backend/ai/gemini_provider.py`. On Python 3.14 (the user's runtime), importing
that SDK fails with `Metaclasses with custom tp_new are not supported`. Because the
provider imports the SDK lazily and degrades gracefully, `GeminiProvider.is_available()`
returns `False`, and every `/chat` and `/parse` request responds with
"El asistente de IA no está disponible" — the AI extraction never runs.

This was reproduced live: `/health` reports healthy with `zabbix_connected: true`, yet AI
extraction is dead on Python 3.14. The fix migrates the provider to the official
`google-genai` SDK (Google Gen AI SDK), which supports Python 3.14, while preserving the
`GeminiProvider` public contract and every non-Gemini behavior.

## Bug Analysis

### Current Behavior (Defect)

When running on Python 3.14 with a `GOOGLE_API_KEY` configured and `ai_provider=gemini`:

1.1 WHEN the process runs on Python 3.14 and `GeminiProvider` is constructed with a valid API key THEN the system fails to import `google-generativeai` (raising "Metaclasses with custom tp_new are not supported") and leaves the model client unset
1.2 WHEN the model client is unset because the SDK import failed THEN the system returns `is_available() == False` even though a valid API key is present
1.3 WHEN a `/chat` or `/parse` request is handled while the Gemini provider is unavailable THEN the system responds with "El asistente de IA no está disponible" and the AI extraction never executes

### Expected Behavior (Correct)

2.1 WHEN the process runs on Python 3.14 and `GeminiProvider` is constructed with a valid API key THEN the system SHALL import the `google-genai` SDK successfully and construct a usable Gemini client
2.2 WHEN a valid API key is present and the `google-genai` client was constructed THEN the system SHALL return `is_available() == True`
2.3 WHEN a `/chat` or `/parse` request is handled with a configured and available Gemini provider THEN the system SHALL run AI extraction and return the parsed `ExtractedRequest` instead of the unavailability message

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `GeminiProvider` is constructed with no API key THEN the system SHALL CONTINUE TO log the missing-key reason (never the secret) and return `is_available() == False`, and `extract()` SHALL CONTINUE TO raise `AIProviderError`
3.2 WHEN the AI SDK is not installed at all THEN importing `backend/ai/gemini_provider.py` SHALL CONTINUE TO succeed (lazy import), `is_available()` SHALL CONTINUE TO return `False`, and `extract()` SHALL CONTINUE TO raise `AIProviderError`
3.3 WHEN the failover layer, factory, or existing tests use `GeminiProvider(api_key, model)`, `is_available()`, and `extract(message, ctx)` THEN the system SHALL CONTINUE TO expose the identical public interface and the same prompt-building (`_build_prompt`/`_fallback_prompt`) and response-parsing (`parse_response_text`) behavior
3.4 WHEN the OpenAI provider is used (`ai_provider=openai`) THEN the system SHALL CONTINUE TO behave exactly as before (the OpenAI provider is not touched by this fix)
3.5 WHEN a Gemini request succeeds THEN the system SHALL CONTINUE TO apply the same generation parameters — temperature 0.2 and max output tokens 1200 — and SHALL CONTINUE TO delegate JSON extraction/parsing to `parse_response_text` without computing Zabbix bitmasks
