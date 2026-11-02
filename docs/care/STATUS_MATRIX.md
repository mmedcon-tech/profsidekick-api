# Built / Tested / External-dependent / Planned

| Area | Built | Tested | External | Planned |
|---|---|---|---|---|
| Program context, verified device line | ✅ | API + e2e (G1) | – | – |
| Typed results (education / needs_clinician / source_unavailable / urgent) | ✅ | API + e2e (G2, G5) | OpenAI for generated text | – |
| Source cards with excerpt, open source pane, transcript | ✅ | e2e (G2) | – | – |
| Video placeholder (no injection footage) | ✅ | e2e | – | Real clinic-approved footage |
| Review requests (idempotent), staff inbox, staff reply labelling | ✅ | API + e2e (G5, staff UI at /care/staff) | – | Real staff paging |
| Supporter invites, scopes, revoke | ✅ | API + e2e (G4) | – | – |
| Safe redirects / open-redirect fix | ✅ | unit + e2e (G7, D) | – | – |
| Program switch isolation (audio, in-flight requests) | ✅ | e2e (G7) | – | – |
| Voice replies (ElevenLabs) | ✅ | e2e A3 audible earlier; graceful 503 path verified | ElevenLabs quota exhausted until 30 Nov (2026-11-02: real call returned 503; UI fallback verified in browser) | Paid tier |
| AI avatar (LiveAvatar) | ✅ (existing) | short manual sessions | LiveAvatar credits low | – |
| Content SHA-256 pins, immutable approved versions, hash-tagged index invalidation | ✅ | API (tests/test_care_integrity.py) | – | – |
| Untrusted-source fencing in prompt, injection-doc test, no tools/web | ✅ | API (stubbed model) | Live model behaviour unverified (no key) | – |
| Invite verifiers (HMAC), expiry/revoke/single-use, rate limits | ✅ | API | – | Shared rate-limit store |
| Auto review request when unanswerable / needs clinician (deduplicated) | ✅ | API + e2e (G5) | – | Real staff paging |
| Passwords: bcrypt cost 12, rehash on login, no timing oracle | ✅ | API | – | – |
| OpenAI-generated answers | ✅ code path | quoted fallback only | **Needs real key** | – |
| Health + admin status | ✅ | API | – | – |
| Telemetry (enum-only) | ✅ | API | – | Dashboard |
| MYOS seed (`scripts/seed_myos.py`, `npm run seed`): 2 workspaces, 4 programs, 3 twins with exact opening lines, idempotent, respects edited_at | ✅ | API (tests/test_myos_redesign.py) | – | Exact section-7 memory text (drafts seeded) |
| Pilot in_review rule (in_review content only in pilot workspaces, shown with its review status) | ✅ | API | Clinician sign-off | – |
| Patient navigation: Home / Talk / Guides / Care team tabs, side nav on desktop, menu, My history, Account settings, Sharing | ✅ | vitest (nav by role) + e2e/myos-guide.mjs | – | – |
| First-run guide (patient 6 / supporter 3 / publisher 5 steps), server-tracked, reopen from menu and Account | ✅ | vitest + e2e/myos-guide.mjs | – | – |
| Arabic toggle (both apps, `dir=rtl`) | ✅ shell, nav, guide, home | e2e | – | Arabic for chat panel and Studio page bodies |
| Studio "Needs your attention" | ✅ | e2e | – | – |
| Page performance (prod build < 1.5 s every page; model first text budget 5 s with fallback) | ✅ | e2e/perf-check.mjs, API tests | Live model timing needs key | Token streaming |
| HIPAA readiness | – | – | BAAs | see HIPAA_BLOCKERS.md |

OpenAPI check (`/openapi.json`, 2026-11-01): 200 paths, 60 under `/api/care`, including context,
tts-authorization, requests (GET/POST), support / support-invitations / support-grants,
invitations/redeem, studio inbox + request actions, studio invitations, health, admin/status,
telemetry/client-event, video playback.
