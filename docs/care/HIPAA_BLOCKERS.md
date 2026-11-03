# Real patient data: open blockers

This deployment is a **synthetic demo**. This file makes no compliance claim. It lists what must be done, and checked
by qualified people, before any real patient data may be used. The server enforces this: when
`MYOS_ENVIRONMENT=production`, the patient routes (`/api/care/c/*`, `/api/care/agent/*`, consultations) return 503
until `health.real_data_gate()` reports no blockers.

| # | Blocker | Status | Owner |
|---|---------|--------|-------|
| 1 | A signed BAA (US) or DPA (EU) with every model, voice and avatar provider that would receive patient data. The registry marks them `baa`/`dpa`. None are marked signed. | Open | Business/legal |
| 2 | Hosting with a BAA/DPA, encryption at rest and in transit, and backups encrypted with key management. Contabo is not assessed. | Open | Ops |
| 3 | A risk assessment and policies (access control, audit review, incident response, breach notification). | Open | Compliance |
| 4 | Retention and deletion rules for chats, care memory, the access log, recordings and transcripts. | Open | Clinic + compliance |
| 5 | Clinical governance: named clinicians approve material using the exact-version approval flow. Right now **no IVF FAQ is clinician-approved**. | Open | Clinic |
| 6 | Third-party agent access (MCP): a security review of token handling and the scopes, and patient-facing terms. | Open | Security |
| 7 | Rotate every key that was pasted into chat during development (OpenAI, ElevenLabs, LiveAvatar/HeyGen, Supabase, Contabo, Gmail). | Open | Owner |
| 8 | Penetration test and a review of cross-clinic isolation. Automated tests cover isolation, but that is not a review. | Open | Security |
| 9 | A named person records the sign-off in `MYOS_REAL_DATA_SIGNOFF` only after 1–8 are closed. | Open | Owner |

**What's already in place (engineering controls, not compliance):**
- per-tenant and per-user cache keys;
- tests for cross-clinic denial;
- personal medication questions are routed to the care team;
- the patient-visible agent access log;
- agent tokens stored only as hashes;
- revocation on the next call;
- the provider registry blocks the `phi` data class without agreements.
