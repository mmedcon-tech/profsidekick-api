# Real-time IVF doctor twin: phased plan

Written 3 Nov 2026. Goal: a patient talks to Dr. Avery (or a real clinic doctor's twin, made with consent) in real time. The twin answers as an IVF educator from clinic-approved material only, hands personal clinical questions to the clinic inbox, and the stack runs 24/7 on the Contabo VPS rather than the laptop.

This document makes no regulatory or compliance claim. Vendor data-processing terms (BAA/DPA) for ElevenLabs, LiveAvatar/HeyGen, OpenAI and Contabo are unknown and listed as blockers.

**Order:** 0 → 1 → 2 → 3 → 4 → 5. Phases 1 and 2 can overlap once Phase 0 is done. Phase 4 (VPS) can start any time the SSH access below is granted.

| Phase | What | Effort (agent time) | Calendar dependency |
|---|---|---|---|
| 0 | Finish the Create doctor avatar flow (T30–T37) with mocks | 1.5–2.5 days | none |
| 1 | IVF expertise: sources, evals, refusals, handoff | 1–1.5 days | clinic approves content |
| 2 | Real-time loop (STT → RAG LLM → streaming TTS → LiveAvatar LITE) | 2–3 days | OpenAI key, LiveAvatar credits |
| 3 | Real doctor likeness (PVC + photo avatar) | 0.5 day of wiring once access exists | plan upgrades, doctor's files and consent |
| 4 | Move to the Contabo VPS, 24/7, redeploy and restart checks | 1 day | SSH key, git remote or rsync approval, Cloudflare token |
| 5 | Hardening: monitoring, backups drill, load test, evals in CI | 1 day | none |

---

## Phase 0: Create doctor avatar flow (T30–T37)

**Scope**
- **T30 Uploads.** Clinic owner or clinical-reviewer only. Select a doctor (DoctorPersona). Upload several headshots and pick the primary one; upload audio (wav/mp3/m4a, or audio from mp4/mov).
  - Image checks (Pillow + OpenCV Haar cascade): one face, roughly centered, reasonable size; a 16:9 or 9:16 aspect ratio and a short side of at least 1080 px (LiveAvatar's documented rule).
  - Audio checks (ffmpeg → WAV, stdlib `wave`): duration, RMS, SNR estimate. Speaker consistency is a labelled heuristic.
  - Originals are stored privately with SHA-256. Anything missing or unsuitable keeps a resumable draft with exact messages.
- **T31 Authorization.**
  - Per-item consent: likeness and voice; providers (ElevenLabs, LiveAvatar/HeyGen); uses (patient education in named programs). Record signer, date, uploaded consent file, scope and version.
  - Live verification is an action the doctor completes in the provider's own flow. **We never generate or synthesize consent or verification recordings.**
  - ElevenLabs PVC route: the doctor creates and verifies the PVC in their own ElevenLabs account and shares it with the clinic account. The clinic pastes the voice ID; we confirm access read-only with `GET /v1/voices/{voice_id}`.
  - Reuse of an existing authorized voice ID is supported. IVC only if the plan allows it and consent covers it.
  - Revocation deletes or detaches the provider voice and avatar and writes an audit event.
- **T32 Visual avatar.** LiveAvatar `POST /v1-alpha/avatars/image` (alpha), then poll `GET /v1/avatars/{id}` until ACTIVE. Docs: https://docs.liveavatar.com/api-reference/avatar/create-image-avatar-alpha
  - Only used when the account has a custom-avatar slot. Otherwise the step shows "Needs plan upgrade" or "Complete in LiveAvatar dashboard" with instructions, and a field to paste the resulting avatar ID to resume.
- **T33 Jobs and storage.**
  - DB-backed job table plus a worker loop: statuses, provider job IDs, an idempotency key per provider call, and in-flight job recovery on restart.
  - Storage interface: local private store now; S3 (boto3, already a dependency) behind `USE_CLOUD_STORAGE`. Signed short-lived preview URLs, no public URLs, secrets server-side.
- **T34 Preview and approval.**
  - Video or audio preview with captions, mute, stop and clear errors.
  - Separate approvals for appearance, voice and pronunciation, with a test list (doctor's name, progesterone, ICSI, …).
  - Patient label: "AI avatar of Dr [name]." Visually distinct from a live consultation and from staff-written messages.
- **T35 Knowledge.** Assign only to programs and courses of the same clinic. Headshots and audio create no knowledge. Retrieval and policy stay server-side and unchanged; the handoff is unchanged.
- **T36 Boundary.** `LIVEAVATAR_PATIENT_DATA_APPROVED=false` by default. While false, LiveAvatar rendering is limited to test accounts (`*@myos.test` or `is_test`). Real patients get text, plus ElevenLabs voice only if `ELEVENLABS_PATIENT_VOICE_APPROVED=true`. Enforced in the session-token endpoint.
- **T37 Tests.** Covers:
  - uploads and validation, the resumable draft;
  - restart recovery, idempotency;
  - consent before any outbound call, revocation;
  - clinic isolation, the boundary flag;
  - source retrieval with the new avatar, the staff-inbox handoff;
  - an e2e with provider mocks, and one ≤30 s stock-avatar session (Judy) with an audio RMS reading and a screenshot.

**(1) The assistant can do now, autonomously:** everything above with provider mocks, plus the read-only checks (subscription, voice lookup, avatar list).

**(2) The user must provide:**
- The doctor's headshots (at least 1080 px short side, 16:9 or 9:16, plain background), 1–3 minutes of clean voice audio, and a signed consent form. For PVC, the doctor's own ElevenLabs account and verification.
- A decision on the production storage location (S3, Supabase Storage or the Contabo disk). Burjeel branding approval before any Burjeel likeness work.

**(3) Extra access and how to grant it safely:**
- The doctor shares the PVC voice to the clinic's ElevenLabs account inside ElevenLabs. Nothing to paste in chat; the voice ID isn't secret.
- LiveAvatar custom-avatar add-on: buy it in the LiveAvatar dashboard. The existing `LIVEAVATAR_API_KEY` in `.env` is then enough.

---

## Phase 1: IVF expertise

**Scope**
- **Sources to approve.** The clinic's own guides (protocols, medication sheets, consent leaflets). Public education to attribute and link: HFEA (hfea.gov.uk) and ASRM ReproductiveFacts (reproductivefacts.org). Each goes through the existing draft → in review → approve flow with a named reviewer and is pinned by SHA-256.
- **Eval set.** About 60 IVF questions in `tests/evals/ivf_questions.json`, each with the expected source item(s) and a must-cite flag. Covers:
  - stimulation, monitoring, trigger, retrieval, ICSI vs IVF, embryo grading in plain terms, transfer, luteal support with progesterone, the two-week wait, OHSS warning signs, egg freezing, costs (clinic content only);
  - Arabic variants.
  - Pass criteria: top-1 or top-3 source match; answer quotes or paraphrases only the cited passage; no dose advice.
- **Refusals.** Personal decisions (dose changes, "should I trigger tonight", reading my scan or bloods, embryo choice) get a fixed refusal that explains why and offers a care-team request. This reuses the existing response policy and red-flag rules; test cases are added to the eval set.
- **Handoff.** "Ask my care team" creates a real CareHandoff in the clinic inbox (existing). The patient sees the actual status (received, assigned, replied). Urgent red flags show the clinic's urgent contact route immediately.

**(1) The assistant can do now:** write the eval set and harness, run retrieval-only evals today (keyword search works without OpenAI), add refusal tests, import HFEA/ReproductiveFacts pages as drafts with source URLs.

**(2) The user must provide:**
- The clinic's own written guides (PDF/DOCX), via Studio "Upload material".
- A clinician reviewer name for approvals. A decision on which public sources are allowed.

**(3) Extra access:** `OPENAI_API_KEY` (rotated, new key) put by you directly into `~/code/mmedcon/profsidekick-api/.env`, never in chat. It unblocks embeddings (vector retrieval) and real generated answers; without it, answers are fallback passages.

---

## Phase 2: Real-time conversation loop

**Pipeline** (all policy server-side)
1. **Browser mic → STT.** Use streaming STT (ElevenLabs Scribe realtime or OpenAI realtime transcription, whichever plan exists), with push-to-talk first and voice activity detection second. Partial transcripts are shown live.
2. **Backend `/care/.../chat` (existing).** Entitlement check, red-flag rules, RAG over approved items for that program, LLM with the existing system policy. Tokens are streamed back over SSE/WebSocket, along with sources.
3. **Streaming TTS.** ElevenLabs `stream` (Flash/Turbo model) is fed sentence by sentence as tokens arrive.
4. **LiveAvatar LITE.** Our own audio is pushed to the avatar session over its WebSocket; LiveAvatar returns lip-synced WebRTC video. Docs: https://docs.liveavatar.com/docs/lite-mode/overview.md and /lite-mode/events.md
   - LITE costs 1 credit/min, FULL 2 credits/min (https://docs.liveavatar.com/docs/faq/credits.md).
   - Test accounts only while the T36 boundary flag is false.
5. **Barge-in.** When the user starts speaking (VAD or a button), stop TTS, send the LiveAvatar interrupt event, cancel the LLM stream, and keep the partial answer in history marked "interrupted".
6. **Fallbacks.** Without LiveAvatar (no credits, flag off, WebRTC blocked): voice only. Without ElevenLabs: text. With no model reachable within 5 s: the existing friendly fallback plus approved passages.

**Latency budget** (target first audio ≤1.5–2.0 s after the user stops speaking)

| Step | Budget |
|---|---|
| End-of-speech detection | 300 ms |
| STT final | 200–300 ms |
| Retrieval (keyword + pgvector) | ≤150 ms |
| LLM first sentence | 500–700 ms |
| TTS first audio chunk | 250–350 ms |
| Avatar lip-sync start | 100–200 ms |

Instrument each step with server timings and log p50/p95 per turn.

**(1) The assistant can do now:** the streaming endpoint, sentence chunker, barge-in state machine, text/voice fallbacks, timing instrumentation, and tests with mocked STT/TTS. One ≤30 s Judy LITE session to measure real lip-sync latency (7.3 credits left).

**(2) The user must provide:**
- The OpenAI key in `.env`.
- An ElevenLabs paid plan: the free tier has 307 characters left this month and cannot sustain voice.
- LiveAvatar credits: Essential at $99/month gives 1,100 credits, about 18 hours of LITE.

**(3) Extra access:** none beyond keys placed in `.env` by the user.

---

## Phase 3: Real doctor likeness

Wire the outputs of Phase 0 into Phase 2:
- The twin's `voice_id` (the PVC shared by the doctor) and `avatar_id` (the LiveAvatar photo avatar).
- Approvals are enforced before activation.
- "AI avatar of Dr [name]." is shown in the call UI and the Details sheet.

**(1) Now:** everything except creating the real voice and avatar.

**(2) The user must provide:**
- The doctor's files and signed consent.
- The doctor completes PVC verification in their own ElevenLabs account and shares the voice.
- An ElevenLabs plan with cloning: PVC needs Creator or higher; per the subscription API, the current free tier allows neither IVC nor PVC.
- The LiveAvatar custom-avatar add-on (an avatar slot).

**(3) Extra access:** none in chat. Plan purchases happen in the vendors' dashboards. A HeyGen API key is only needed if you want HeyGen studio videos as well; put it in `.env` as `HEYGEN_API_KEY`.

---

## Phase 4: Contabo VPS, running 24/7

**Target layout** (Docker Compose on the VPS)
- `postgres` (pgvector), with a named volume.
- `redis`.
- `backend` (FastAPI) and `memory-worker` / `avatar-worker`.
- `frontend` (`next build` + `next start`).
- `caddy` or `nginx` reverse proxy.
- Cloudflare in front: DNS proxied, SSL mode "Full (strict)", origin certificate on the proxy.
- All services get `restart: unless-stopped` and Docker healthchecks (`/health` for the API, `/login` for the frontend, `pg_isready`). Docker itself is enabled at boot (`systemctl enable docker`).

**Backups**
- Nightly `pg_dump -Fc` via cron to `/var/backups/myos` with 14-day retention.
- Weekly copy off-box (S3/Supabase/another host, your choice).
- Monthly restore drill into a scratch database, the same as the local `mig_restore` drill.
- Uploads: copy the private store with rsync on the same schedule.

**How to verify the VPS restarted and is healthy**
- `uptime` (boot time and load) and `last reboot | head -3` (reboot history).
- `docker ps --format '{{.Names}} {{.Status}}'`: every service "Up … (healthy)" with an uptime matching the reboot.
- `curl -fsS https://<domain>/api/health` and `curl -fsS -o /dev/null -w '%{http_code}' https://<domain>/login` both return 200.
- `systemctl status docker` and `journalctl -b -u docker --no-pager | tail`.
- Contabo Customer Control Panel → VPS → status "Running" (and a "Restart" log entry if it was rebooted from there).
- Optional: an external uptime monitor on the health URL.

**Redeploy procedure**
1. Get code onto the VPS. Either a **private git remote**, or **rsync over SSH** from the Mac. Both need your explicit approval, because the current rule is "no remotes".
2. `docker compose build && docker compose up -d`.
3. `docker compose exec backend alembic upgrade head`, after a fresh `pg_dump`.
4. Health checks as above.
5. Rollback: `git checkout <previous tag>` (or the previous rsync snapshot), then `docker compose up -d` and `alembic downgrade -1` if needed.

**(1) The assistant can do now:** write `docker-compose.prod.yml`, the Caddy/nginx config, healthchecks, a backup cron script, `scripts/deploy.sh` and `scripts/verify_vps.sh`, all tested locally. The VPS itself can't be touched until access is granted.

**(2) The user must provide:** the domain, a decision on the backup destination, and production `.env` values written on the VPS by you (or copied by `scp` from the Mac). Never in chat.

**(3) Extra access and how to grant it safely:**
- **SSH:** on the VPS as root, create a non-root `deploy` user in the `docker` group and add the box's public SSH key (which I will print, public half only) to `/home/deploy/.ssh/authorized_keys`. Disable password login (`PasswordAuthentication no`). Do not share the root password; the one pasted in chat earlier should be changed.
- **Code transfer:** approve either a private GitHub/Origin remote (push from the Mac only) or rsync to `deploy@vps:/srv/myos`.
- **Cloudflare:** an API token scoped to *Zone:DNS:Edit* for that one zone only, put in the VPS `.env` or the vault, not chat. Or you add the DNS record yourself.
- Vercel/GitHub access only if you choose to host the frontend there instead of the VPS.

---

## Phase 5: Hardening
- Uptime monitor and alerting.
- Log rotation.
- A load test of 20 concurrent chats.
- Evals in CI.
- A backup restore drill.
- Rotate every credential that appeared in chat (OpenAI, Gemini, Contabo, Supabase, Gmail).

(1) Assistant: all scripts and tests. (2) User: rotations. (3) Access: same as Phase 4.

---

## Blockers (current)
- No OpenAI key: no embeddings or generated answers.
- ElevenLabs free tier: no cloning, 307 characters left.
- LiveAvatar free plan: 7.3 credits, no custom-avatar slot.
- No HeyGen key.
- S3 credentials are placeholders.
- No VPS access.
- Vendor BAA/DPA status unknown.
- The exposed OpenAI and Gemini keys are still to be rotated.

## Consolidated checklist

| Item | Why needed | Who provides | How to provide safely | Unblocks |
|---|---|---|---|---|
| New OPENAI_API_KEY | Embeddings, generated answers, realtime STT option | Terezia | Type it into `profsidekick-api/.env` (and the VPS `.env`); never chat | Phase 1 evals with vectors, Phase 2 |
| Rotate OpenAI, Gemini, Contabo, Supabase, Gmail credentials shown in chat | They were exposed | Terezia | In each vendor dashboard | All, safety |
| ElevenLabs Creator+ plan | PVC/IVC, enough characters for voice | Terezia | Buy in the ElevenLabs dashboard; existing key in `.env` | Phase 2 voice, Phase 3 |
| Doctor's PVC shared to the clinic account | Real doctor voice with the doctor's own verification | Doctor | Doctor shares the voice in ElevenLabs; paste the voice ID in Studio | T31, Phase 3 |
| LiveAvatar custom-avatar add-on + credits | Photo avatar, real-time video | Terezia | Buy in the LiveAvatar dashboard | T32, Phase 2 video, Phase 3 |
| HeyGen API key (optional) | Only for HeyGen studio videos | Terezia | `.env` `HEYGEN_API_KEY` | Optional |
| Doctor headshots, voice audio, signed consent | Likeness inputs and permission | Doctor / clinic | Upload in Studio "Create doctor avatar" | T30, T31 |
| Clinic IVF guides + clinician reviewer | Approved knowledge | Clinic | Studio "Upload material", reviewer approves | Phase 1 |
| Storage decision (S3 / Supabase Storage / Contabo disk) + its credentials | Private uploads in production | Terezia | Credentials in `.env` on the VPS | T33 prod, Phase 4 |
| Burjeel branding approval | Use of the hospital name and likeness | Burjeel | Written approval on file | Burjeel go-live |
| SSH key for a non-root `deploy` user | Deploy and verify the VPS | Terezia | Add the public key to `authorized_keys`; no root password | Phase 4, 5 |
| Approval for a private git remote or rsync | Get code to the VPS | Terezia | Explicit "yes" naming which | Phase 4 |
| Cloudflare token (Zone:DNS:Edit, one zone) or manual DNS | HTTPS and domain | Terezia | VPS `.env` / vault | Phase 4 |
| Domain name | Public URL | Terezia | Tell me the name (not secret) | Phase 4 |
| Vendor BAA/DPA review | Real patient data with vendors | Terezia / legal | Outside this system | Turning T36 flags on for real patients |
