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
| H9 | Clinical review of all content and safety rules by licensed clinician | Open (fictional reviewer) | Clinical |
| H10 | Identity proofing for patients/supporters beyond invite codes | Open | Product |
| H11 | Pen test + dependency scan | Open | Security |

Current environment is labelled demo everywhere and uses synthetic data only.
