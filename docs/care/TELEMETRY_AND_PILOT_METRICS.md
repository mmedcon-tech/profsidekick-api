# Telemetry and pilot metrics

Client events go to `POST /api/care/telemetry/client-event` (frontend `src/lib/careTelemetry.ts`). The schema is
allowlisted enums only — no free text, no clinical content, optional result_type and request_id.

Event kinds: playback_ok, playback_failed, autoplay_blocked, tts_unavailable, tts_unauthorized,
avatar_started, avatar_failed, avatar_stopped, context_switch, stale_reply_dropped, chat_error,
handoff_created, source_opened, video_placeholder_shown.

## Pilot metrics
| Metric | Source | Target (pilot) |
|---|---|---|
| Share of questions answered as education with ≥1 source | chat results | ≥70% |
| needs_clinician rate, and false-negative audit on sampled personal questions | results + manual review | 0 missed in sample |
| Review request time-to-acknowledge / time-to-reply | request events | within stated clinic hours |
| Source open rate | source_opened | track |
| Voice playback success | playback_ok / (ok+failed+blocked) | ≥95% |
| Avatar start success, session length | avatar_* | ≥90%, ≤ budget |
| Stale replies dropped on switch | stale_reply_dropped | track (should be >0 only on switches) |
| Supporter invites redeemed / revoked | support grants | track |
| Errors by kind (health error_kind) | health/admin status | track |
