# PROPAGA architecture

This document walks the system top to bottom: what each piece does, why it sits
where it sits, and what concrete problem each decision solved.

> Public snapshot. Omitted: the production prompts
> ([`prompts.py`](../apps/publications/prompts.py)), the implementations of the
> five integrations ([`publishers.py`](../apps/publications/publishers.py)) and
> the full error diagnosis table for their APIs. All three files document what
> they replace. See [LICENSE](../LICENSE).

---

## 1. The underlying problem

PROPAGA turns one video into five publications. That sounds like a loop over a
list of APIs, and it isn't, for three reasons:

1. **The work is long.** Downloading a 15-minute video, extracting audio,
   transcribing it, generating copy and transcoding are minutes of CPU and
   network. No HTTP request survives that.
2. **The work is heterogeneous.** The five networks share neither the upload
   protocol, nor the auth model, nor the text limits, nor the accepted codecs.
   Each one is a separate integration with its own ways of failing.
3. **The work fails partially.** YouTube accepting the video says nothing about
   what X will do. A design that treats propagation as an all-or-nothing
   transaction takes away the posts that actually succeeded.

Everything else follows from these three.

---

## 2. Topology

Four processes, one Docker image, differentiated by the `PROPAGA_ROLE` variable
that [`scripts/entrypoint.sh`](../scripts/entrypoint.sh) reads:

| Process | Role |
|---|---|
| `web` | Django + Gunicorn. Serves HTTP. Never invokes ffmpeg, never uploads a byte to a social network. |
| `worker` | Celery. Everything slow and everything that can fail against third parties. |
| `beat` | Celery beat. Scheduled tasks. |
| `redis` | Celery broker (DB 0) + Django cache and locks (DB 1). |
| `db` | PostgreSQL: the source of truth for state. |

**Why one image for four roles.** Coolify doesn't allow overriding an image's
`CMD` from its UI for Dockerfile-type applications. Instead of maintaining four
nearly identical Dockerfiles — and risking that they drift apart — the entrypoint
reads `PROPAGA_ROLE` and decides which process to launch. One image, built once,
tested once, starting in four modes.

**Why the worker has a different healthcheck.** A Celery worker doesn't listen on
any port. A `curl` to the HTTP endpoint would mark it *unhealthy* forever and
Coolify would abort the deploy. For that role, Celery itself is asked over the
broker with `celery inspect ping`.

---

## 3. The pipeline: `process_publication`

Lives in [`apps/publications/tasks.py`](../apps/publications/tasks.py). Takes a
`publication_id` and carries it from `PENDING` to `AWAITING_APPROVAL`.

### 3.1 Three locks before starting

```
Redis lock (1h TTL)  →  SELECT ... FOR UPDATE  →  file lock (flock)
```

Three locks look like paranoia; each covers a different hole:

- **Redis** catches the cheap case: the task is already running in another
  worker, so it returns without touching the database.
- **`select_for_update`** closes the race between reading state and writing it,
  inside the same transaction.
- **`flock`** on the temp directory protects the filesystem, which is the
  resource Redis doesn't know exists.

The Redis lock TTL is **one hour**, not ten minutes. With the previous value the
lock expired *while the task was still alive* and a second worker started the
same publication: two downloads, two transcodes and, worst case, two posts to the
same network. The lock is released in the `finally`; the TTL only exists for the
case where the process dies without running it.

### 3.2 Getting the video

Two paths: an uploaded file (copied into the temp directory) or a URL (yt-dlp).

The yt-dlp format selector does not ask for `bestvideo+bestaudio`:

```
bestvideo[vcodec^=avc1][height<=1080]+bestaudio[acodec^=mp4a]/
best[ext=mp4][height<=1080]/
bestvideo[height<=1080]+bestaudio/best
```

`bestvideo+bestaudio` brought back AV1 or VP9 in 4K with Opus audio — gorgeous,
and necessarily re-encoded in full with `libx264` at the final step, because no
network accepts it that way. Asking for H.264/AAC ≤1080p **at download time**
turns that final transcode into a stream copy. The download also uses four
parallel fragments: multi-minute downloads drop to tens of seconds.

### 3.3 Audio extraction: optimize for Whisper, not for ears

```
-vn -ac 1 -ar 16000 -c:a libmp3lame -b:a 32k
```

Whisper resamples internally to 16 kHz mono. Extracting high-quality audio is
work thrown in the bin. Dropping it to 16 kHz mono / 32 kbps shrinks the file
about 8×: **16 minutes of video go from ~30 MB to ~4 MB**, with no loss of
accuracy.

That matters because 30 MB is above Groq's 25 MB limit *and* above the SDK's
default write timeout, which blew up large uploads with a `Connection error`
after two silent retries.

Hence also the explicit timeouts on the Groq client
(`connect=10s, read/write/pool=300s`) instead of the defaults.

### 3.4 Transcription and generation

Groq/Whisper returns the text. That text goes into the prompt assembled by
[`prompts.build_content_prompt()`](../apps/publications/prompts.py), and Gemini
returns JSON with `title`, `description` and `hashtags`.

Two details:

- **JSON is requested by API contract** (`responseMimeType: application/json`),
  not scraped out of a markdown block in the response.
- **There's a deterministic fallback.** If Gemini fails — quota, timeout, a 500
  from the provider — `generate_fallback_content()` builds a title and
  description by trimming the transcript. The user already waited through the
  download, the extraction and the transcription: getting that far and dying in
  `FAILED` because a third party had a bad minute is the worst possible outcome.
  Degrading beats breaking.

Which model is used, and with which key, is not hardcoded: it comes from
[`integrations.get_provider_config()`](../apps/publications/integrations.py),
which reads the encrypted row in the database and falls back to the environment.

### 3.5 Releasing the user before the transcode

State moves to `AWAITING_APPROVAL` **as soon as the copy is ready**, before
calling ffmpeg. The copy is what the user wants to review; the video keeps
optimizing in the background.

That `save()` used to happen after the encode (because `set_step()` only persists
`processing_step`), so the dashboard sat on "Processing" for every minute
`libx264` took on the full video, and looked hung.

### 3.6 Transcode: remux when possible

`_es_compatible_redes()` runs `ffprobe` and looks at the container's real codecs.

- **Already H.264 + AAC** → `-c copy -movflags +faststart`. Seconds.
- **Not** → `libx264 -preset veryfast -crf 23`, AAC audio at 128k,
  `-pix_fmt yuv420p`. Minutes.

`yuv420p` isn't decorative: X rejects other pixel formats. `+faststart` moves the
`moov` atom to the front so the video starts playing without downloading in full.

The point: most videos already arrive compatible (thanks to the yt-dlp selector
in 3.2), so the expensive path is the exception, not the rule.

---

## 4. Propagation: `propagate_publication`

Walks the target accounts and publishes to each network with its own protocol.

### 4.0 Orchestration and publishers: why they're separate

The Celery task **doesn't know** how a video gets uploaded to X. It only knows
who to ask. `publishers.PUBLICADORES` maps an allauth provider to a
`(label, function)` tuple, and the task iterates:

```python
for account in target_accounts:
    entrada = PUBLICADORES.get(account.provider)
    if entrada is None:
        continue                      # provider without a publisher: skipped
    etiqueta, publicar = entrada
    try:
        publication.set_step(...)
        publicar(publication, account, social_token, video_path)
        published_successfully_count += 1
    except Exception as e:
        fallos.append((etiqueta, str(e)))
```

The five integrations share nothing but that contract: different auth model,
different transport, different text limits. The only thing they share is *when*
they're called. Mixed into the task, a change to the TikTok flow meant re-reading
YouTube's error handling.

The benefit collected immediately: **the orchestration can be tested without
touching a single API.** Dispatch, partial success, failure accumulation,
accounts without tokens, unknown providers and residue cleanup are eight tests
with fake publishers. See `testing/test_03_social_propagation.py`.

> ⚠️ In this public snapshot the bodies of the five publishers are omitted: they
> are the core of the product. `publishers.py` documents each network's full
> protocol — phases, auth, traps, what gets persisted — and every function raises
> `ImplementacionOmitida`. Since that exception travels the same path as any
> network failure, the partial-success flow can still be walked end to end.

### 4.1 Five networks, five protocols

| Network | Auth | Upload protocol |
|---|---|---|
| **YouTube** | OAuth 2.0 (Google) | Google API resumable upload, `MediaFileUpload(chunksize=-1)`. Thumbnail is separate, and its failure doesn't take down the publication. |
| **Facebook** | OAuth 2.0 (Graph) | `POST multipart` to `/{page_id}/videos` with the **page token**, not the user's — you have to resolve it first via `/me/accounts`. |
| **Instagram** | Facebook page token | `REELS` container → **polling up to 6 min** → `media_publish`. The API downloads the video from a public URL. |
| **X (Twitter)** | **OAuth 1.0a** | Four phases: `INIT` → `APPEND` in 4 MB chunks → `FINALIZE` → poll `processing_info` → tweet with `media_ids`. |
| **TikTok** | OAuth 2.0 | `publish/video/init` reserves the space and returns an `upload_url` → `PUT` the bytes with `Content-Range`. |

Three quirks that cost time to discover:

**X requires OAuth 1.0a.** The `media/upload` endpoint doesn't accept the OAuth
2.0 signature from API v2. That's why the `SocialApp` stores Consumer Key/Secret
(25 and 50 characters) rather than the Client ID/Secret pair, which is what you
reach for by reflex in the developer console.

**Instagram has no login of its own.** Its Basic Display API died on 2024-12-04.
Publishing happens on the professional IG account (Business or Creator) linked to
a Facebook page, using that page's token. The app resolves the IG account by
walking `/me/accounts`, preferring the same page the user picked for Facebook.

**The Reels API won't accept the file.** It downloads the video from a public
URL. The worker copies the video into `MEDIA_ROOT`, builds the URL from the
current `Site` domain, waits for processing, and **deletes the copy in a
`finally`** — success or not. An orphaned public video on disk is a content leak,
not just a space problem.

### 4.2 Partial success

```python
if published_successfully_count > 0:
    publication.status = 'PUBLISHED'
    publication.error_message = _resumir_fallos(fallos)
```

If at least one network accepted the video, the state is `PUBLISHED` — something
went out. But the failures from the others are **persisted on the row and shown
in the UI**. It used to mark success and let the errors die in the worker logs:
the user believed they had published to five networks when it had been four.

If all of them failed, the state is `FAILED` with the full detail.

### 4.3 Translating API errors into instructions

`insufficient authentication scopes` tells a user nothing. Nor most developers,
the first time.

`_resumir_fallos()` keeps a table of `marker in the error → what the user has to
do`, and composes an actionable message with the technical detail underneath, in
case whoever's reading can parse it.

> ⚠️ In this snapshot the table is trimmed to two entries. The real one is
> considerably longer: it's the sediment of every distinct way Google, Meta, X
> and TikTok reject an upload.

---

## 5. Data model

[`apps/publications/models.py`](../apps/publications/models.py)

**`Publication`** — the central aggregate. Beyond the video and the generated
copy, it stores **the ID and URL of the post on each network**
(`youtube_video_id`, `facebook_video_url`, `instagram_permalink`,
`twitter_tweet_url`, `tiktok_video_id`…). Explicit columns per network rather
than a generic JSON blob: each network returns an identifier with different
semantics, and these fields are the proof that the post exists out there.

Each ID is written with `save(update_fields=[...])` **immediately after** that
network responds, not at the end of the loop. If the next network blows up or the
worker dies, whatever already went live stays recorded.

`status` is the macro state; `processing_step` is the sub-step the worker writes
at each phase. `get_progress_steps()` combines them into the list the UI paints,
marking each step `done` / `active` / `pending` — and for the publishing phase it
builds the steps **in the same iteration order** as `propagate_publication`, so
the progress bar doesn't lie.

**`AIConfiguration`** — one-to-one with the user: persona, free-form
instructions, fixed hashtags, hashtag count, emojis on/off. The persona lives in
the database, not in code: changing the AI's register needs no deploy and every
user has their own.

**`APIIntegration`** — provider, encrypted key, model and the status of the last
connection test.

---

## 6. Security

**Keys encrypted at rest.** Fernet with a key derived from `SECRET_KEY` via
SHA-256. The `masked_key` property is the only thing that reaches the UI and the
logs (`••••` + last 4). If `SECRET_KEY` rotates, decryption fails cleanly, the
reason is logged, and it falls back to the environment instead of blowing up.

**`SECRET_KEY` and `GEMINI_API_KEY` have no defaults.** The process won't start
without them. A server that boots with an example key is worse than one that
doesn't boot.

**No host wildcards in production.** `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`
come from the environment. Development tunnels (ngrok/cloudflared) — mandatory
for testing OAuth, because Meta, Google and TikTok demand a public HTTPS callback
— are enabled **only under `DEBUG`**.

**Hardened cookies outside `DEBUG`:** `Secure`, `HttpOnly`, `SameSite=Strict`.

**No `set -x` in the entrypoint.** Bash's trace would print every variable
expansion into the container logs, and `DB_PASSWORD` and the broker URLs pass
through there.

**Rootless container.** User `propaga` (uid 1000), created in the Dockerfile.

**Per-user isolation.** Every view filters by `user=request.user`; a
`get_object_or_404(Publication, pk=pk, user=request.user)` returns 404 — not 403 —
for someone else's publication: it doesn't confirm the resource exists.

**Real scope verification.**
[`social_permissions.py`](../apps/publications/social_permissions.py) asks
Google's `tokeninfo` what permissions the token actually carries, because allauth
doesn't store them. The result is cached for 10 minutes with the token hash
inside the key: on reconnect the token changes, the lookup lands on a different
key, and nothing has to be invalidated by hand. On a network error it caches
empty for 60 seconds — you can't assert the permission is missing, but you can't
confirm it either — and retries soon.

---

## 7. Frontend: HTMX, no SPA

There is no JavaScript build. Every user action returns an already-rendered HTML
fragment, and HTMX swaps it into the DOM. The `HX-Trigger` header fires
client-side events (`missionApproved`, `changesSaved`) to open the progress view
or show confirmations.

**Why.** A publication's state lives in PostgreSQL and Redis: a Celery worker
writes it, not the browser. With an SPA you'd have to maintain a parallel API
contract and synchronize state on the client that the client doesn't own. With
server-rendered fragments, a video being processed looks the same in every tab
and on every device, for free.

The design system is CSS custom properties (`static/css/tokens.css` +
`design-system.css`) with Tailwind compiled in a separate Dockerfile stage — no
CDN at runtime. Light/dark theme with persistence.

---

## 8. Deployment

A **three-stage multi-stage Dockerfile**:

1. **tailwind-builder** (alpine) — compiles the utility CSS. No CDN in production.
2. **builder** (python-slim) — installs dependencies into a virtualenv with the
   build toolchain.
3. **runtime** (python-slim) — copies the virtualenv and the compiled CSS. Only
   `libpq5`, `ffmpeg` and `curl`. Non-root user.

Final image ~500 MB. The previous version, with PyTorch and local Whisper,
weighed ~5 GB: moving transcription to the Groq API removed 4.5 GB of image and
the GPU requirement.

The entrypoint actively waits for PostgreSQL and Redis (30 attempts, 1 s each),
runs migrations and `collectstatic`, and syncs the OAuth credentials from the
environment into allauth's `SocialApp` rows with `seed_social_apps`. That last
step is idempotent and **never takes down the deploy**: if it fails, it's logged
and the boot continues, because a deploy that dies over optional seeding is worse
than a deploy with stale OAuth.

---

## 9. Tests

Two suites, with different purposes.

**`tests/` and `apps/*/tests*.py`** run under `manage.py test`, against an
ephemeral database the runner creates and destroys. They verify domain logic and
deployment configuration: that the database is PostgreSQL, that the broker is
Redis, that `ALLOWED_HOSTS` carries no wildcards, that no non-TLS CSRF origin
points outside the local machine, and that templates use the design-system tokens
rather than loose colors (`apps/publications/tests_design_system.py`).

**`testing/`** are standalone scripts that run against the real database,
precisely because they verify things an ephemeral database cannot assert: that
`MEDIA_ROOT` is writable, that Redis is alive, that the `SocialApp` rows are
loaded. Run them all with `python testing/run_all.py`.

Calls to external APIs and to ffmpeg are mocked: what's verified is the state
flow and the error handling, not whether Meta is online. The ffmpeg mock
**creates the output files** rather than just returning `returncode=0` — a mock
that only says "it worked" makes the code blow up later for a reason that has
nothing to do with what's under test.

`testing/test_04_downloads.py` does hit the network: yt-dlp is the most fragile
dependency in the system, YouTube shifts the ground under it every few weeks, and
no mock warns you about that. For the same reason it doesn't run by default — a
test that depends on a third party can't fail the CI of a change that never
touched it. Enable it with `PROPAGA_NETWORK_TESTS=1`.

> **A note on these scripts.** While preparing this snapshot, the suite reported
> green with a broken test inside: the scripts exited 0 even when `unittest`
> recorded failures, and `run_all.py` decides by the return code. Underneath was
> a mock pointing at `call_deepseek_api`, a function that stopped existing when
> the generator moved to Gemini. A test that cannot fail is not a test.
> `utils.run_suite()` is the fix.

**`apps/testing_ui/`** is a panel inside the admin for running the tests and
reading the results without leaving the browser.

---

## 10. What this snapshot doesn't show

- The **production prompts**: seven personas tuned against real transcripts. The
  prompt architecture is documented in
  [`prompts.py`](../apps/publications/prompts.py); the texts are not.
- The **implementations of the five publishers**: the exact sequence each API
  accepts and the order it accepts it in. Each network's protocol is documented
  in [`publishers.py`](../apps/publications/publishers.py); the code is not.
- The **full error diagnosis table** for those APIs.
- Credentials, tokens and user data.
- The real deployment pipeline (build to GHCR + Coolify webhook): this snapshot
  is frozen and deploys nowhere.
