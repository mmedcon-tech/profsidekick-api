# HIPAA blocker register (must be closed before any real patient data)

| # | Blocker | Status | Owner action |
|---|---|---|---|
| H1 | BAA with OpenAI (or Azure OpenAI with BAA, zero data retention) | Open | Legal/procurement |
| H2 | BAA with ElevenLabs (enterprise tier) or self-hosted TTS | Open | Procurement |
| H3 | BAA with LiveAvatar or remove avatar for PHI sessions | Open | Procurement |
| H4 | Hosting with BAA (AWS/GCP/Azure HIPAA account); Railway/Fly not covered | Open | Infra |
| H5 | Encryption at rest for Postgres + backups; key management | Open | Infra |
| H6 | Audit log retention policy (6 yr) and tamper evidence | Partial (audit rows exist) | Eng |
| H7 | Risk assessment, policies, workforce training, breach procedure | Open | Compliance |
| H8 | Real staff routing: requests currently land in a demo queue, no paging/SLA | Open (demo-simulated) | Clinic ops |
| H9 | Clinical review of all content and safety rules by licensed clinician | Open. Seeded MYOS content is `in_review` with reviewer "Awaiting clinician"; it is visible only in pilot workspaces (`is_pilot`), never in a live clinic, until a named clinician approves it | Clinical |
| H10 | Identity proofing for patients/supporters beyond invite codes | Open | Product |
| H11 | Pen test + dependency scan | Open | Security |
| H12 | Invitation/redeem rate limits are in-process memory only; multi-worker deploys need a shared store (Redis) | Open | Eng |
| H13 | Content hash pins detect tampering at read time but the DB itself has no write-ahead signing / WORM audit storage | Open | Eng/Infra |
| H14 | Prompt-injection defence is fencing + instructions + no tools; it reduces but cannot eliminate model compliance with malicious source text. Source review by clinicians stays mandatory | Open (mitigated) | Clinical/Eng |
| H15 | Supporter access to AI chat is enforced server-side by the `chat_history` scope (get_consultation, send_message); supporter UI hides Talk/History but the API is the control | Built, tested (`test_supporter_cannot_open_conversations`) | Eng |
| H16 | Exposed OpenAI and Gemini keys must be rotated by the owner before any further use | Open | Owner |

2026-11-02: integrity work (hash pins, HMAC invite verifiers, rate limits, bcrypt rehash) is engineering hardening only. It does **not** make the system HIPAA compliant and no compliance claim is made.

Current environment uses synthetic data only. Since 2026-11-02 the interface no longer shows "fictional" or "(demo)" labels; instead each item carries its real review status (in review / approved, reviewer, date), and the pilot rule below limits where unapproved content can appear.

## Pilot in_review rule (2026-11-02)
- Patients see `approved` content everywhere. They see `in_review` content **only** when the clinic workspace is flagged as a pilot. Draft and retired content is never shown.
- Source cards for in_review items show "reviewed by Awaiting clinician" so nobody mistakes them for approved material.
- Test: `tests/test_myos_redesign.py::test_in_review_content_only_visible_in_pilot_workspaces`.
- This is a product rule, not a compliance control. It does not close H9.
