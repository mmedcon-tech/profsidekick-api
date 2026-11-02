# MYOS care platform — task register

Branch: `myos-care-checkpoint` (local only, no upstream, never pushed). Owner "agent" = Grok Bot executor; "Terezia" = needs the user.
Status: done · blocked · open. Attempts are capped at 3 (see AGENT_RUNBOOK.md). Evidence = test name / command result.
Test DB for pytest: `DATABASE_URL=postgresql://postgres:postgres@localhost:5435/profsidekick_test`.

| ID | Pri | Task | Depends | Owner | Acceptance check | Status | Attempts | Evidence |
|---|---|---|---|---|---|---|---|---|
| T0 | P0 | Fresh DB backup before migrating | – | agent | dump file exists | done | 1 | `~/myos-backups/pre_integrity_20261102_0719.dump` |
| T1 | P0 | SHA-256 content pin on approval; approved rows immutable; edits fork a version | T0 | agent | pin == recomputed hash; in-place edit raises | done | 1 | `test_approval_pins_sha256_and_tags_chunks`, `test_approved_content_is_immutable_in_place` |
| T2 | P0 | Invalidate chunks/embeddings on change; retrieval only serves chunks tagged with the pinned hash and items that still re-hash to the pin | T1 | agent | tampered/stale/expired/superseded never returned | done | 1 | `test_changed_hash_removes_old_passages_from_retrieval`, `test_new_version_invalidates_old_index_and_expiry`, existing `test_draft_expired_superseded_not_retrievable` |
| T3 | P0 | Transcripts bound to hash + version; patient playback returns pinned transcript only | T1 | agent | transcript_sha256 in playback | done | 1 | `test_signed_video_link_dies_when_video_retired` |
| T4 | P0 | Reversible migration a1c2e3f4b5d6 tested upgrade→downgrade→upgrade on isolated restore, then live | T1–T3 | agent | alembic head on restore + live; 16/16 approved items pinned, 0 untagged chunks | done | 1 | container `care-restore` on :5440 (removed after), live `alembic current` = a1c2e3f4b5d6 |
| T5 | P0 | Invite verifier = HMAC-SHA256(SECRET_KEY), constant-time compare, 80-bit codes, legacy SHA-256 rows still redeem | – | agent | no plaintext/plain-hash stored | done | 1 | `test_invite_verifier_is_keyed_and_not_plaintext`, `test_legacy_sha256_invite_still_redeems` |
| T6 | P0 | Invite expiry, revocation, single-use, same 404 for every invalid state | T5 | agent | 404s identical | done | 2 (test read wrong error key) | `test_invite_expiry_revocation_single_use`, existing `test_supporter_invite_scoped_own_account_revocable` |
| T7 | P0 | Rate limits: redeem 10/15 min, create 30/h per user (429 + Retry-After) | T5 | agent | 11th redeem → 429 | done | 1 | `test_invite_redeem_and_create_rate_limited` (in-process store: H12) |
| T8 | P1 | Passwords: audit (38/38 users bcrypt $2b$12), cost 12, rehash weaker hashes at login, non-bcrypt never verifies, dummy check for unknown users | – | agent | rehash test | done | 1 | `test_password_hashing_bcrypt_and_rehash_on_login` |
| T9 | P0 | Document-only retrieval: clinic+program+course+audience+entitlement, approved+unexpired+pinned; no tools/web | T2 | agent | cross-clinic doc never retrieved | done | 1 | `test_injection_doc_from_other_clinic_never_retrieved`, existing `test_cross_clinic_and_course_isolation` |
| T10 | P0 | Untrusted-source fencing (<<<SOURCE n>>>, forged delimiters neutralised, ignore-instructions rule) | T9 | agent | injection doc test | done | 1 | `test_injection_laden_document_is_fenced_as_untrusted` |
| T11 | P0 | Media links purpose-bound (patient vs studio) and dead once video is not approved | – | agent | retired video link → 404; patient link can't become studio link | done | 1 | `test_signed_video_link_dies_when_video_retired` |
| T12 | P0 | Auto review request when source_unavailable / needs_clinician; dedupe by idempotency key AND by same open question | – | agent | one case per question | done | 2 (e2e attempt 1 found auto+manual duplicate; fixed server-side) | `test_unanswerable_question_files_durable_deduplicated_request`; e2e rerun created 0 new rows for a repeated question |
| T13 | P0 | Staff-only ack/reply; replies marked `author_type=human_staff`; chat messages `ai`/`clinic_text`/`patient` | T12 | agent | non-staff 403/404 | done | 1 | `test_only_authorized_staff_ack_and_reply_marked_human`; e2e G5_patient_sees_staff_reply |
| T14 | P1 | Frontend: show auto-filed request status/assignee/expectation in chat; author_type type; 16-char code placeholder | T12 | agent | tsc clean, vitest green | done | 1 | tsc 0 errors; vitest 368/368 |
| T15 | P1 | Browser audio: real call or 503 fallback visible | – | agent | audio-state=failed with tts 503, nothing plays | done (fallback) | 1 | e2e A3_*: real ElevenLabs call returned 503 (quota) |
| T16 | P1 | Program switching: no leaked messages/audio | – | agent | API + browser | done | 1 | `test_program_switch_does_not_leak_messages`; e2e G7_switch_mid_play_and_request |
| T17 | P1 | Supporter access limited + revocable; sign-in return flow | – | agent | e2e | done | 1 | e2e G4_jake_scope, G4_jake_after_revoke, G7_return_after_signin, D_open_redirect_blocked |
| T18 | P1 | Avatar (LiveAvatar LITE) connected to care chat | – | agent | session starts/stops | done earlier, not re-run | 0 this round | verified in previous round; skipped now to save free-plan credits |
| T19 | P0 | Live OpenAI answers (grounding, injection ignored, needs_clinician) | key | Terezia | `verify_care_llm.py --rebuild` exit 0 | **blocked** | 1 | `profsidekick-api/.env` and the running container both still have a placeholder (exit 2). The .env she described (mathAutograder DB) is not this repo's .env and was not found on disk |
| T20 | P2 | Real voice | ElevenLabs quota | Terezia | audible RMS > 0 | **blocked** | – | quota resets 30 Nov or paid plan |
| T21 | P2 | Shared rate-limit store for multi-worker | – | agent | – | open | 0 | H12 |
| T22 | P2 | Move e2e script into repo | – | agent | file in repo | done | 1 | `profsidekick-frontend/e2e/care-demo.mjs` (credentials read from /tmp, not committed) |

## Round: MYOS redesign follow-ups (2026-11-02)

- [ ] T23 (HIGH, do first after checkpoint) Performance: measure Studio + patient pages on `next dev` :3000 and prod build :3001 (Playwright timing, `curl -w`, backend logs), model time vs rest; record before table. Fix N+1, indexes, unbounded lists (pagination), waterfalls (combined dashboard endpoint), heavy bundles (dynamic import of three.js / avatar-1.glb), per-tenant/per-user reference caching, embedding in request paths; stream model replies, timeouts <= 5 s with friendly fallback. No new deps, no weaker entitlement checks. Add `e2e/perf-check.mjs` (fail > 5 s). Report before/after.
- [ ] T24 UX navigation review `docs/UX_NAVIGATION_REVIEW.md` (frontend): GfG UX principles, audit of current patient + Studio nav, changes mapped to principles.
- [ ] T25 Patient nav: "Talk to [twin]" primary above fold; mobile bottom tabs (Home · Talk · Guides · Care team) + menu; desktop visible side nav; active state, labelled icons, one title/primary button per page, actionable empty states, contrast, 44px targets, focus, aria. "My history" page.
- [ ] T26 Studio drawer with active state; dashboard leads with "Needs your attention".
- [ ] T27 First-run guide (custom, no dep), server-tracked `onboarding_completed_at` (API done: GET/POST /api/care/me/onboarding); Skip/Back/Next/Done; reopen from menu "How MYOS works" + Account settings; spotlight + small-screen card; patient/supporter/publisher variants; RTL + i18n; vitest + Playwright; screenshots per step.
- [x] T28 Supporters cannot open or post to the AI conversation (server-side `chat_history` scope check).
