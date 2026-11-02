# Doctor avatar: plan check (2 Nov 2026, read-only, no keys printed)

## ElevenLabs (GET /v1/user/subscription)
- Tier: free. can_use_instant_voice_cloning = false, can_use_professional_voice_cloning = false, professional_voice_limit = 0.
- Characters: 9,693 of 10,000 used (307 left).
- Result: no voice clone call of any kind is allowed. IVC and in-account PVC both show "Needs plan upgrade". The "doctor shares a PVC from their own account" path still works without a clinic upgrade: we only GET /v1/voices/{id} to confirm access.

## LiveAvatar (GET /v1/users/credits, GET /v1/avatars)
- 7.3 credits left, 0 custom avatars.
- Free tier: $0, 10 credits/month, no overage. Essential: $99, 1,100 credits. Business: $475, 6,000 credits. FULL mode costs 2 credits/min, LITE 1 credit/min. Source: https://docs.liveavatar.com/docs/faq/credits.md
- Image avatar: POST /v1-alpha/avatars/image (alpha). The image must be exactly 16:9 or 9:16 with a short side of at least 1080px and one clearly framed person. Poll GET /v1/avatars/{id} until ACTIVE. 1080p needs Business. Sources: https://docs.liveavatar.com/api-reference/avatar/create-image-avatar-alpha and https://docs.liveavatar.com/changelog
- Custom avatars are a paid add-on and need an avatar slot. Image avatars need no consent recording and include no voice; a voice comes from the library, custom TTS, or LITE with our own audio. Video avatars need 2 minutes of footage plus a consent recording. Source: https://docs.liveavatar.com/docs/core-concepts/avatars
- Result: avatar creation shows "Needs plan upgrade (avatar slot add-on)". No creation calls were made.

## HeyGen
- No HEYGEN_API_KEY in the backend env (only HEYGEN_ENABLED). Not usable.

## Libraries in the backend image
- Present: Pillow, boto3.
- Absent: numpy, opencv, mediapipe, face_recognition, pydub, mutagen. ffmpeg is not in the container or on the Mac.
- Face count and centering therefore need a new dependency (question for Terezia). Audio checks without new dependencies are limited to WAV, using stdlib `wave` and `audioop`-style RMS.

## Storage
- USE_CLOUD_STORAGE=false and the S3 credentials are placeholders. This is a blocker; dev uses the local private store.
