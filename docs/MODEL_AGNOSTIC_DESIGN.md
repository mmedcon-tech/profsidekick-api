# MYOS model-agnostic design

Status: implemented on branch `myos-care-checkpoint` (commits f890623, bbaf6d2, c7315c6, cc56b70, 21db1b8).
This document describes how MYOS keeps clinical behaviour independent of any one AI vendor.
It makes no HIPAA or other compliance claim; see `docs/care/HIPAA_BLOCKERS.md`.

## 1. Principles

1. **MYOS owns the clinic's knowledge and the clinical rules.** Retrieval, approval, versioning,
   safety gates, citations and handoffs run in MYOS code. A model only phrases an answer from
   passages MYOS selected.
2. **Models are replaceable workers.** Website, MCP and clinical code never import a model SDK or
   name a model. They call `app.services.ai.clinical` (`complete`, `embed`, `ready`).
3. **Eligibility before availability.** A provider is used for a request only if the registry says it
   may process that clinic's data class for that capability. Fallback never widens that set.
4. **Honest status.** Unknown agreements are recorded as `unknown`, never assumed.

## 2. Knowledge Hub (per clinic)

- `care_content_items`: one row per version of a clinic item (FAQ, patient instruction, document,
  video transcript). Fields that govern serving: `clinic_id`, `program_id`, `audience`
  (patient | caregiver | both | staff), `status` + `approved_sha256` (exact-version approval),
  `expires_at`, `effective_from` / `effective_to`, `applicability` (`stages: a, b` limits an item to
  treatment stages), `source_url`.
- `care_content_chunks`: passages cut from the approved text, each tagged with `item_sha256` and
  `embedding_model`. Retrieval only compares vectors produced by the active embedding model.
- Patient-facing retrieval (`content.retrieve`) filters: session clinic + program, audience,
  visible status, approved hash match, integrity check, expiry, effective dates, entitled courses,
  treatment stage. Staff-audience items never reach patients; passages written as instructions for
  the assistant (`guidance.split`) steer the model but are never shown, cited or quoted.
- Export: `scripts/export_clinic_kb.py <clinic-slug>` writes `myos.clinic-knowledge.v1` JSON
  (items, versions, approvals, digest; no embeddings, no patient data).
- Reindex: `scripts/reindex_embeddings.py [--clinic slug]` re-embeds chunks whose
  `embedding_model` differs from the active one (run after switching embedding provider).

## 3. ModelProvider contract (`app/services/ai/base.py`)

```
generate(messages, *, model, timeout, temperature, schema=None) -> Generation
stream(messages, *, model, timeout, temperature) -> AsyncIterator[str]
embed(texts, *, model, timeout) -> list[list[float]]
```

`Generation` = text, provider, model, parsed (validated against an optional pydantic schema),
usage, provider_request_id. Every adapter maps its failures to MYOS errors
(`app/services/ai/errors.py`):

| kind | meaning | retried / fallback? |
|---|---|---|
| auth | key rejected (401) | no; breaker opens |
| access | key valid, project/model not permitted (403, 404 model_not_found) | no; breaker opens |
| quota | billing / credit exhausted | no; breaker opens |
| rate_limited | 429 | yes |
| timeout | deadline passed | yes |
| unavailable | 5xx / connection | yes |
| parsing | empty or malformed response, schema mismatch | yes |
| config | key missing | no |
| not_eligible | no eligible provider | never |

Logs carry the category and the provider's request id only (never prompt or answer text).

Adapters: `openai_adapter.py` (the only care-path module importing the OpenAI SDK) and
`local_adapter.py` (deterministic, offline; used for tests and the switching demo).
A second hosted provider can be added with httpx against its HTTP API; no new SDK is needed.

## 4. Registry (`app/services/ai/providers.json`, `registry.py`)

Per provider: adapter, account label, key env var name (never the key), endpoint, region,
agreements (`baa`, `dpa`: signed | not_signed | unknown), retention, review dates, and per
capability (`generation`, `embeddings`, `voice`, `transcription`, `avatar`) an enabled flag and the
data classes it may process (`public_content`, `synthetic`, `phi`).

`registry.eligible()` returns the first blocking reason: provider_disabled, capability_not_enabled,
model_not_approved, data_class_not_permitted, baa_not_signed, dpa_not_signed.
Routing lists an ordered chain per capability (and optionally per clinic).
`clinic_data_class` maps a clinic to its data class: demo clinics and declared-synthetic clinics are
`synthetic`; everything else defaults to `phi`, which no provider is currently eligible for.

Current honest status: OpenAI and ElevenLabs agreements `unknown`; both limited to
public_content and synthetic. Real patient data is therefore refused before any call.

## 5. Router and fallback (`router.py`)

1. Build the chain for (clinic, task) and drop every ineligible entry (recorded as `skipped`).
2. Try eligible entries in order within one shared deadline. Non-retryable errors open a
   per-provider breaker. Retryable ones move to the next eligible entry.
3. Every attempt writes one op-log event (`myos.model_ops`): request id, clinic slug, task,
   data class, provider, model, outcome, error kind, provider request id, fallback_from/reason,
   latency, token counts. An allow-list in `oplog.py` drops any other field, so text cannot be logged.
4. Embeddings use only the first eligible provider (vectors from different models are not mixed).

## 6. Patient answer path (care chat)

intent router (greeting / model status) -> safety gates (emergency, red flags, personal
treatment decisions) -> unverified device check -> retrieval from the clinic's Knowledge Hub ->
prompt (platform rules > clinic guidance and sources > persona style; clinic contact routes) ->
router -> citation validation (invented [n] removed; one card per document; only cited cards shown).

If no eligible model answers: an **approved** patient FAQ with a clear match is quoted under
"From your clinic's FAQ"; otherwise a short message with the "Ask my care team" action.
No disguised or unlabelled answer is ever produced.

## 7. Switching providers (config only)

Edit `routing` in `providers.json` (or call `registry.set_config` in tests) - no code change.
`tests/test_model_agnostic.py` proves on a synthetic flow that switching between the OpenAI and
local adapters changes only the provider, for: a general IVF answer, an injection-video question
and a conflicting-dose escalation (escalation never calls a model). An outage simulation shows
patient (phi) requests are never sent to an ineligible fallback. A lint test fails if website,
MCP or clinical modules import a model SDK or name a model.

## 8. What still needs the clinic / owner

- A second real provider key and its signed BAA/DPA before it can be marked eligible.
- Signed agreements with any provider that will process real patient data (`phi`).
- Clinician approval of the IVF FAQ set (currently "in clinical review"), which the model-down
  FAQ fallback needs.
