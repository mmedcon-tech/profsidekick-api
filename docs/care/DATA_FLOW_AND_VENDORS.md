# Data flow and vendor inventory (MyOS Care demo)

```
Browser (Next 15, :3000)
  ├─ /api/care/* ───────────────► FastAPI (:8000) ──► Postgres (care tables, requests, grants, audit)
  │                                   ├──► OpenAI chat (question + approved passages)  [only if key set]
  │                                   └──► (health) ElevenLabs /v1/models, /v1/user/subscription
  ├─ /api/tts/elevenlabs (Next route) ─► ElevenLabs TTS (assistant reply text only)
  └─ LiveAvatarLite ─────────────────► LiveAvatar (session + reply audio) ≤30 s demo sessions
```

| Vendor | Data sent | Patient data? | Contract status |
|---|---|---|---|
| OpenAI | user question, approved clinic passages, program context | yes if real users | No BAA — **blocker** |
| ElevenLabs | assistant reply text | indirectly (replies may echo context) | No BAA — **blocker**; free tier, quota-limited |
| LiveAvatar | reply audio/text, session metadata | indirectly | No BAA — **blocker** |
| Postgres (self-hosted Docker) | all care records | yes | infra only |
| Railway/Fly (deploy targets in repo) | everything at rest | yes | No BAA — **blocker** |

Not sent anywhere external: supporter invite codes (hashed), review-request staff notes, telemetry
(enum-only, see TELEMETRY_AND_PILOT_METRICS.md).
