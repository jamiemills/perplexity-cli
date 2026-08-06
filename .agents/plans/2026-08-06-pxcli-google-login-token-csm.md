# pxcli Google-Login Token Acquisition CSM Plan

## How To Execute
- Start work only through a separate, explicit `csm-build` invocation naming this plan; the planning session must not begin execution.
- Commit policy and live state are maintained in Control by csm-build.
- Risk summary: 6 tasks. T001 (feasibility spike) and T003/T004 (Google sign-in with real credentials) are high-risk: they authenticate to a live external service and handle a real Google identity. T001 must complete with evidence before any credential use. The user cannot interact with the browser, so T003 pauses at an explicit approval gate (user approves on their phone via Google prompt / YouTube app) and T004 has a bounded approval budget. Two BLOCKER mechanics were remediated from critique: the webgl browser needs an explicit CDP driver (csm-browse cannot launch without --disable-webgl), and the pxcli bridge cannot use host socat (absent on the host) — replaced with a host Python forwarder; the direct-injection fallback is the expected-path alternative.

## Control
- Plan ID: pxcli-google-login-token
- Status: ready
- Current CSM state: NOT_STARTED
- Cycle: 0
- Commits: allowed (credential-bearing files must remain gitignored; only docs/plan/scripts are committed)
- Last checkpoint: 2026-08-06 — plan drafted, critiqued (2 blockers + 6 majors), remediated, verified
- Next transition: On a future explicit csm-build invocation, NOT_STARTED -> RECOVER
- Active tasks: none
- Blockers: none

## Goal
Establish a working Perplexity CLI (`pxcli`) auth token by performing a Google sign-in to perplexity.ai in an automated browser session inside the `chromium-vnc` Docker container, with the sign-in approved by the user on their phone, and persist the resulting token into pxcli's encrypted token store. The login email lives in a git-ignored `.env` file. The user cannot interact with the browser directly, so the plan drives it via CDP and stops at explicit approval gates.

Deliverables:
1. A proven browser login to perplexity.ai via Google (email `jamie.mills@gmail.com` from `.env`, phone-approval gate).
2. A valid pxcli token persisted via `pxcli auth login` (or the documented direct-injection fallback), verified with `pxcli auth status --verify`.
3. Credentials confined to a git-ignored `.env`; no secrets in git, logs, or commits.

Constraints:
- The browser is driven entirely by automation (csm-browse verbs / CDP). The only human input is the Google sign-in approval on the user's phone.
- The login email is read from `.env` (`PERPLEXITY_GOOGLE_EMAIL`), which is already gitignored (`.gitignore:41-42`). The existing `.env` (holds CI `SAFETY_API_KEY`) is appended to, never overwritten, never committed, never logged.
- `pxcli auth login` is the primary token-grab mechanism (user requirement); a direct `TokenManager` injection is the documented fallback if CDP bridging fails.
- No changes to pxcli source or other analysers; this plan is operational (runs the existing CLI), plus an optional gitignored helper script for reading `.env`.

Exclusions:
- No modification of pxcli's auth code, token format, or encryption.
- No targeting of the container's primary shared browser (port 9222) for automation (csm-browse skill rule).
- No storing the password (only the email) — Google sign-in approval is done on the user's phone; no password is handled.
- No committing `.env`, tokens, cookies, or screenshots containing credentials.

## Acceptance Criteria
1. T001 spike proves, with recorded evidence, whether a webgl-enabled headful Chromium (replicating the csm-browse environment) can reach the perplexity.ai login page past Cloudflare. Outcome documented as PASS (login page reachable) or BLOCK (automated path infeasible from this environment). If BLOCK, the plan stops at that gate and the user decides the fallback.
2. `PERPLEXITY_GOOGLE_EMAIL` exists in `.env`, `.env` is confirmed gitignored, and the automation reads the email without printing it.
3. The browser navigates to perplexity.ai, clicks "Sign in" → "Continue with Google", enters the email, and reaches the Google approval step. The plan PAUSES and reports to the user for phone approval (the user's only interaction).
4. After user approval, the browser returns to perplexity.ai and `localStorage["pplx-next-auth-session"]` is present (token captured; cookies captured with `save_cookies` enabled).
5. `pxcli auth status --verify` succeeds (live API check) after token acquisition via `pxcli auth login --port <bridged>` (or the documented direct-injection fallback).
6. Cleanup: browser session closed; `git status` shows no `.env`, no token.json, and no credentials in the working tree or staged changes; a final evidence report is produced.

## Current-State Evidence
- `pxcli auth login --help` (observed): connects via Chrome DevTools Protocol to a running Chrome on port 9222 (default), navigates to Perplexity.ai, waits for the user to log in, extracts the session token, and stores it encrypted at `~/.config/perplexity-cli/token.json`. It does NOT open a browser. `--port` is configurable (`src/perplexity_cli/commands/auth_cmds.py:49-60`); host is hardcoded `localhost` (`src/perplexity_cli/auth/oauth_handler.py:82`).
- Token extraction (research): priority 1 = `localStorage["pplx-next-auth-session"]` (the re-serialised JSON blob, used as the Bearer token); priority 2 = `__Secure-next-auth.session-token` / `next-auth.session-token` cookies (`oauth_handler.py:536-620`). All browser cookies are captured (`Network.getAllCookies`), incl. Cloudflare `cf*` cookies, but only persisted if `save_cookies` is enabled (default off; `token_manager.py:120-127`, config default `save_cookies: false`).
- Token storage (research): `TokenManager.save_token(token, cookies)` -> `<config_dir>/token.json`, v2 `{"version":2,"encrypted":true,"token":"<fernet v2>","created_at":...,"cookies":...}`, mode 0600, machine+user-bound encryption key `PBKDF2-HMAC-SHA256(salt, hostname:USER)` (`utils/encryption.py:33-43`). `pxcli auth status --verify` does a live API call (`runners/status.py:167-187`).
- `pxcli auth login` polls up to `DEFAULT_AUTH_TIMEOUT = 120`s for the token (`config/defaults.py:43`), then exits 1 on timeout.
- `.env` exists (52 bytes, only `SAFETY_API_KEY`), gitignored (`.gitignore:41-42`). pxcli does NOT read `.env` (no python-dotenv dependency; `pyproject.toml` deps 31-42) — the automation must source it itself.
- csm-browse skill: launches an isolated Chromium in the `chromium-vnc` container (CDP on container ports 9224-9234, public on `172.17.0.2:<port>`), driven via `browse.mjs` verbs; VNC on host `localhost:5900` is observational only. Skill rule: never target the primary shared browser (port 9222).
- PROVEN BLOCKER (planning R&D): the csm-browse isolated browser is launched with `--disable-webgl --disable-gpu --disable-accelerated-2d-canvas --disable-dev-shm-usage --hide-scrollbars` (full flag list incl. `--ozone-platform-hint=auto --no-sandbox --password-store=basic --enable-software-rasterization --remote-debugging-address=0.0.0.0`; `~/.config/opencode/skills/csm-browse/lib/constants.mjs:30-42`). Navigating to `https://www.perplexity.ai` from it shows a Cloudflare "Just a moment..." Turnstile challenge (`cf-turnstile-response` hidden input, value empty) that does NOT auto-resolve after ~90s, reloads, and offers no interactive element. Browser probe reports `webgl:false`. Host `curl` to perplexity.ai also returns HTTP 403. Conclusion: the webgl-disabled automated browser cannot pass Cloudflare.
- Google sign-in flow (knowledge + csm-browse verbs): a "Continue with Google" button triggers an accounts.google.com OAuth redirect; with 2-Step Verification the account can approve via a phone prompt (e.g. YouTube app) — exactly the approval the user described. The automation can type the email and click Next; the user approves on their phone; the browser then redirects back to perplexity.ai and the session appears.

## Assumptions And Decisions
| ID | Statement | Type | Evidence or rationale | Status |
|----|-----------|------|-----------------------|--------|
| A1 | The login browser must pass Cloudflare; the csm-browse isolated browser (webgl disabled) is PROVEN blocked | Evidence | Turnstile never resolves after ~90s; `webgl:false`; flags in constants.mjs:30-42 | Confirmed |
| A2 | A webgl-enabled chromium (replicating the csm-browse env, software GL/swiftshader, no disabling flags) may pass Cloudflare; this is UNPROVEN and is T001's spike | Decision | Webgl is a known Turnstile fingerprint signal; ad-hoc container launch was inconclusive due to environment plumbing | Accepted (spike) |
| A3 | Token acquisition uses `pxcli auth login --port <host-forward>` (user requirement); direct `TokenManager.save_token()` injection is the documented fallback | Decision | pxcli CDP needs host-localhost; bridge via host socat; fallback avoids the fragile bridging | Accepted |
| A4 | `save_cookies` must be enabled before login so Cloudflare `cf*` cookies persist for later CLI use | Decision | cookies dropped unless `save_cookies` true (token_manager.py:120-127) | Accepted |
| A5 | Email stored as `PERPLEXITY_GOOGLE_EMAIL` in the existing gitignored `.env`; automation sources it; never logged | Decision | `.gitignore:41-42`; no password handled (phone approval) | Accepted |
| A6 | The logged-in perplexity tab must be the first page target when `pxcli auth login` runs (it navigates the first page target) | Evidence | oauth_handler.py:101-118,331 | Accepted |
| A7 | If the container IP is Cloudflare-flagged such that no browser passes, the automated path is infeasible and the plan stops at the T001 gate for user direction | Decision | Host curl 403 suggests IP-level suspicion is possible | Accepted |
| A8 | Browser driving uses csm-browse verbs where possible; a webgl-enabled session (if required) is launched via a small helper replicating the csm-browse environment, on a port pool beyond 9224 | Decision | csm-browse flags are fixed in the skill; helper keeps the skill untouched | Accepted |

## R&D Record
| ID | Question | Method/tool | Isolation and no-change evidence | Observation | Plan implication |
|----|----------|-------------|----------------------------------|-------------|------------------|
| R1 | Does the csm-browse isolated browser reach perplexity.ai? | csm-browse session `pxcli-plan`; open perplexity.ai; wait/reload; inspect `cf-turnstile-response`, webgl probe | Browser session only; no credentials; session closed after | Cloudflare "Just a moment" Turnstile; token stays empty ~90s; `webgl:false`; no interactive element | csm-browse browser is BLOCKED; T001 spike must prove a webgl-enabled browser |
| R2 | How does pxcli extract/store a token? | Read oauth_handler.py, token_manager.py, encryption.py, runners/auth.py, auth_cmds.py | Read-only | CDP to host-localhost:9222 (port configurable); polls `pplx-next-auth-session` localStorage or next-auth cookies up to 120s; stores encrypted machine-bound token.json (0600); cookies only if save_cookies on | Token-grab via `pxcli auth login --port`; enable save_cookies; bridge CDP to host-localhost |
| R3 | Does pxcli support `.env`? | grep dotenv/load_dotenv in src + pyproject | Read-only | No dotenv dependency; env must be exported by the driving shell | Automation sources `.env` itself; keep it gitignored |
| R4 | Can a webgl-enabled chromium in the container pass Cloudflare? | Ad-hoc chromium launch in container (attempted) | Disposable /tmp profile; no credentials | Inconclusive: chromium environment plumbing (XDG/HOME/user) wasn't replicated; devtools not reliably reachable | T001 must replicate the full csm-browse env (env vars, user 1000, DISPLAY :0) with modified flags; document as spike |
| R5 | What does Google sign-in + phone approval look like to the automation? | Knowledge of accounts.google.com OAuth + csm-browse verbs | n/a | type email -> Next -> phone prompt -> auto-redirect back to perplexity.ai -> session created | T003 automation stops at the approval gate; T004 polls for completion |

## Discovered Requirements
- The driving shell must source `.env` (`set -a; . ./.env; set +a`) and pass the email to the `type` verb as an argument from `PERPLEXITY_GOOGLE_EMAIL`; never echo it.
- Enable `PERPLEXITY_SAVE_COOKIES=true` (or `pxcli config set save_cookies true`) BEFORE `pxcli auth login` so Cloudflare cookies persist.
- Bridging to pxcli's hardcoded `localhost` host requires a HOST forwarder: `socat` is NOT installed on the host (verified `which socat` -> not found; it exists only inside the container), so a small inline Python forwarder (host-localhost:<port> -> 172.17.0.2:<container port>) is used instead. Chrome advertises `ws://localhost:<internalPort>` (the csm-browse skill rewrites it via `.replace('localhost', ip)`; pxcli does NOT rewrite — `oauth_handler.py:71`), so the forward must cover the exact advertised port: launch chromium with `--remote-debugging-address=0.0.0.0 --remote-debugging-port=<port>` inside the container, then forward host-localhost:<port> -> 172.17.0.2:<port>; pre-check the advertised `webSocketDebuggerUrl` and forward that exact host:port. If any bridging step fails, use the T005 direct-injection fallback.
- Before running `pxcli auth login`, close any other tabs so the logged-in perplexity tab is the FIRST page target.
- Use ONE fixed browser session id for T003-T005 and do NOT run `ensure-browser`/`--cleanup-stale` for other session ids in between: the skill sweeps sessions idle >10 min on the next `ensure-browser` of a different sid, which would kill the logged-in session during phone approval.
- The `type` verb echoes typed text to stdout, and `cookies`/`eval` verbs print values — use leak-safe eval expressions (e.g. `(localStorage.getItem('pplx-next-auth-session')||'').length`), name-only cookie processing, and NO screenshots while the email field is filled.
- The `cookies` verb returns the raw CDP cookie array; `TokenManager` needs `dict[str,str]` (`token_manager.py:310-314`) — transform `{c['name']: c['value'] for c in cookies}` before any direct-injection save, and pass the token to the host command via an env var or a 0600 temp file, never argv/ps.
- T004 approval wait is bounded (total budget ~15 min) then STOP and report with options; never loop indefinitely.
- `pxcli auth login` waits up to 120s; the login must already be complete (T004 done) so the poll finds the token immediately.
- A webgl-enabled browser (if needed) must run as user 1000 with `DISPLAY=:0`, `HOME`/`XDG_*` pointed at a session dir, plus `--use-gl=swiftshader`/`--enable-unsafe-swiftshader` for software WebGL (the container has no GPU), `--remote-debugging-address=0.0.0.0` for host reachability, and NO disabling flags. Port 9231+ to avoid csm-browse's 9224-9235 public range. It must be driven by an inline gitignored driver (chrome-remote-interface from the skill's node_modules) because csm-browse cannot launch it.
- No image-viewing is available to this model: verification uses DOM/text/cookie probes, not screenshots; screenshots (if any) are for the user's VNC/eyes only and must not contain credentials.
- `.env` must never be staged (`git status` check in T006).

## Design
Stage-by-stage operational flow, each stage a gate:

1. **T001 Feasibility spike (make-or-break).** Stand up a webgl-enabled headful Chromium inside `chromium-vnc` replicating the csm-browse environment (user 1000, `DISPLAY=:0`, session HOME/XDG dirs, socat to host) but WITHOUT the fingerprint-revealing flags (`--disable-webgl`, `--disable-gpu`, `--disable-accelerated-2d-canvas`) and WITH software GL. Verify `webgl` is present (probe). Navigate to `https://www.perplexity.ai` and poll the `cf-turnstile-response` / page title for up to ~60s. Record PASS (login page reachable) or BLOCK. On BLOCK, STOP and report to the user for direction (the automated path is infeasible from this IP; recommend the user log in via their own host browser and import the token).

2. **T002 Credentials.** Append `PERPLEXITY_GOOGLE_EMAIL=jamie.mills@gmail.com` to `.env`; confirm `.env` is gitignored and untracked; add a tiny gitignored loader snippet in the driving commands (no new committed file required — the shell sources `.env` inline).

3. **T003 Google sign-in initiation.** In the browser, `open https://www.perplexity.ai`, then discover selectors at runtime via `text`/`html` (page is dynamic; selectors are not hardcoded in the plan), click "Sign in", click "Continue with Google", `type` the email from `.env` into the Google email field, click "Next". STOP at the approval gate and report to the user: "Approve the sign-in on your phone." (This is the user's only interaction; per their instruction, seek approval here.)

4. **T004 Complete login.** Poll (wait-selector/text) until accounts.google.com redirects back to perplexity.ai AND `localStorage["pplx-next-auth-session"]` is non-empty (via the browser eval verb). If the user's approval is slow, re-prompt. Capture evidence: token presence, cookies via the `cookies` verb, page state. Keep this tab as the only/first page target.

5. **T005 Token acquisition into pxcli.** Enable `PERPLEXITY_SAVE_COOKIES=true`. Bridge the session CDP to host-localhost with a host `socat` forward and run `pxcli auth login --port <port>`; confirm `[OK] Authentication successful!` and token.json written. If the bridge or ws-URL fails, use the fallback: read `localStorage["pplx-next-auth-session"]` + cookies via browser verbs, then a host-side one-off script (gitignored, or inline `uv run python -c`) that calls the CLI's own `TokenManager.save_token(token, cookies)` so the machine-bound encryption matches. Verify `pxcli auth status --verify`.

6. **T006 Cleanup + evidence.** Close the browser session (csm-browse `close` / kill the spike browser + socats), delete any temp profiles under `/tmp`/container session dirs, confirm `git status` shows no `.env`/token/cookie artifacts, and produce the final evidence report (auth status output, token.json existence + perms, no-secrets check).

Bridging detail (T005): (1) launch the webgl chromium with `--remote-debugging-address=0.0.0.0 --remote-debugging-port=<port>` so it binds 0.0.0.0 (reachable at 172.17.0.2:<port> from the host); (2) run a host inline Python forwarder `host-localhost:<port> -> 172.17.0.2:<port>` (host `socat` is absent); (3) `curl http://localhost:<port>/json/version`, read the advertised `webSocketDebuggerUrl`, and ensure that advertised host:port is also forwarded to the container; (4) run `pxcli auth login --port <port>`. If any step fails (or the ws URL is unresolvable), use the direct-injection fallback: read `localStorage['pplx-next-auth-session']` (length-only probe) and the cookie name/value pairs via leak-safe means, transform cookies to `dict[str,str]`, and run a one-off host command (same host/user so the machine-bound encryption matches) calling `TokenManager.save_token(token, cookies)` with the token passed via env var, nothing committed.

## Execution Graph
Dependencies:
```
T001 (feasibility spike)  [G1]  depends: none
T002 (.env credentials)   [G2]  depends: T001 (must pass) — parallel-safe with T003 setup but kept sequential for approval clarity
T003 (initiate Google)    [G3]  depends: T001, T002
T004 (complete login)     [G4]  depends: T003 (user approval)
T005 (pxcli token)        [G5]  depends: T004
T006 (cleanup + evidence) [G6]  depends: T005
```
Critical path: T001 -> T002 -> T003 -> (user approval) -> T004 -> T005 -> T006. Largely sequential by nature (each stage depends on the previous); no safe parallel implementation groups except none. T002 is trivial and could run before T001, but sequencing it after the spike gate avoids touching credentials until feasibility is proven.

## Numbered Plan
1. [pending] Feasibility spike: prove a webgl-enabled browser can reach the perplexity login page past Cloudflare
   - Task ID: T001
   - Depends on: none
   - Parallel group: G1
   - Risk: high (external service; determines the whole approach)
   - Owned scope: a disposable webgl-enabled chromium session inside the `chromium-vnc` container (port 9231+), a host socat forward, /tmp scratch — NO repo files
   - Not in scope: any credential use, any modification of csm-browse skill or pxcli
   - Spike candidate: (this task IS the spike) — Question: "Does a webgl-enabled chromium replicating the csm-browse environment pass the perplexity.ai Cloudflare challenge?" Isolation: session HOME/XDG under a /tmp profile in the container; network GET only; no credentials; terminate processes at the end.
   - Actions: (1) Write a gitignored inline driver under /tmp using `chrome-remote-interface` (already in the csm-browse skill's node_modules — set `NODE_PATH` to the skill's `node_modules`); (2) launch chromium inside the container as user 1000 with `DISPLAY=:0`, session HOME/XDG dirs, and the FULL flag set: `--no-sandbox --no-first-run --password-store=basic --disable-dev-shm-usage --ozone-platform-hint=auto --enable-software-rasterization --use-gl=swiftshader --enable-unsafe-swiftshader --remote-debugging-address=0.0.0.0 --remote-debugging-port=9231` and NO `--disable-webgl`/`--disable-gpu`/`--disable-accelerated-2d-canvas`/`--hide-scrollbars`; (3) probe webgl (should be present via swiftshader); (4) first navigate to a NEUTRAL control site (e.g. https://example.com) to prove the browser env itself works before judging Cloudflare; (5) then navigate to https://www.perplexity.ai and poll title/`cf-turnstile-response` up to 60s. Record PASS (login page / Sign-in reachable) or BLOCK (challenge persists), and capture the validated launch recipe as the task deliverable for reuse by T003.
   - Acceptance signal: a recorded probe result — either (a) the page title leaves "Just a moment..." / the sign-in button is present (PASS), or (b) the Turnstile response stays empty for 60s (BLOCK), each with exact DOM evidence, PLUS the validated launch recipe (exact command + driver) reproduced for T003.
   - Validation: webgl context present on the control site and on perplexity; host reaches `http://172.17.0.2:9231/json/version` (chromium bound 0.0.0.0); `text`/`html` of final state captured; no credentials touched.
   - Acceptance evidence: recorded PASS/BLOCK verdict, DOM evidence, and the reusable launch recipe; no credentials.
   - Repair attempts: 0
   - Recovery note: if the browser launch fails (env plumbing), replicate the exact csm-browse env (HOME/XDG_CONFIG_HOME/XDG_CACHE_HOME/XDG_RUNTIME_DIR set to session dirs, user 1000, `DISPLAY=:0`) — `ensure-browser.mjs` is the reference. If the verdict is BLOCK, STOP; do not proceed to T002.

2. [pending] Store the Google email in the git-ignored `.env`
   - Task ID: T002
   - Depends on: T001 (must be PASS)
   - Parallel group: G2
   - Risk: low (credential handling — must not leak)
   - Owned scope: `.env` (append-only), no other files
   - Not in scope: committing `.env`, printing the email
   - Spike candidate: none
   - Actions: Append `PERPLEXITY_GOOGLE_EMAIL=jamie.mills@gmail.com` to the existing `.env` (preserving the existing `SAFETY_API_KEY` line; the file ends with a newline so append is safe). Verify `.env` is gitignored (`git check-ignore .env`) and untracked (`git status`). Verify `SAFETY_API_KEY` is STILL present and unmodified after the append (guards corruption/overwrite). Confirm the email reads back from a sourced shell without echo.
   - Acceptance signal: `git check-ignore .env` succeeds; `git status --short` shows no `.env`; `grep -c PERPLEXITY_GOOGLE_EMAIL .env` == 1; `grep -c SAFETY_API_KEY .env` == 1.
   - Validation: source the file and assert `PERPLEXITY_GOOGLE_EMAIL` is set; confirm the value is NOT printed to any log.
   - Acceptance evidence: check-ignore output, git status, key count.
   - Repair attempts: 0
   - Recovery note: if `.env` were somehow tracked, `git rm --cached .env` (only if it is already committed — verify first; do not touch the working file contents beyond the append).

3. [pending] Initiate the Google sign-in and stop at the phone-approval gate
   - Task ID: T003
   - Depends on: T001, T002
   - Parallel group: G3
   - Risk: high (real authentication; user interaction gate)
   - Owned scope: the browser session only
   - Not in scope: completing sign-in, any password handling
   - Spike candidate: none
   - Actions: In the webgl-enabled browser, `open https://www.perplexity.ai`; wait for the login surface; discover the "Sign in" and "Continue with Google" selectors at runtime (`text`/`html` — do not hardcode); click "Sign in"; click "Continue with Google"; on the accounts.google.com page, set the email field value (from `PERPLEXITY_GOOGLE_EMAIL`, sourced from `.env`) via a leak-safe `eval` that reads a page-scoped JS value (the `type` verb echoes typed text to stdout — do NOT use it for the email; if `eval`-injection is not viable, accept and explicitly exclude that one command's output from all logs/evidence); click "Next". Then STOP and report to the user: sign-in initiated; approve on your phone (Google prompt / YouTube). Do NOT continue to T004 until the user confirms approval.
   - Acceptance signal: the accounts.google.com page reaches a state where Google is awaiting the approval (e.g. a "Use your phone to sign in" / verification prompt is displayed), captured via `text`.
   - Validation: confirm the email field was filled (length/domain check via eval, never echoing the address); do NOT screenshot while the email field is filled (a screenshot would contain the email) — screenshot before typing or skip; capture the approval-pending page text.
   - Acceptance evidence: the approval-pending page text; the browser session remains open.
   - Repair attempts: 0
   - Recovery note: if Google blocks the sign-in from this environment ("unusual traffic"/"browser not secure"), STOP and report — this is the R2 fallback decision point (user may need to sign in from their own browser).

4. [pending] Complete the login after user phone approval
   - Task ID: T004
   - Depends on: T003 (user confirms approval)
   - Parallel group: G4
   - Risk: medium
   - Owned scope: the browser session only
   - Not in scope: token extraction (T005)
   - Spike candidate: none
   - Actions: Poll (bounded: total budget ~15 min, checked every ~10s) until the browser redirects back to perplexity.ai and `localStorage["pplx-next-auth-session"]` is non-empty, using ONLY leak-safe eval expressions (e.g. `(localStorage.getItem('pplx-next-auth-session')||'').length`); re-prompt the user once if approval is slow. On budget expiry, STOP and report with options (re-prompt, re-enter email, or abandon). Capture evidence leak-safely: token LENGTH, cookie NAMES only (values never printed). Use the SAME fixed session id as T003 and run no other-sid `ensure-browser`/`--cleanup-stale` in between (the skill sweeps idle sessions >10 min). Ensure this logged-in tab is the ONLY/first page target.
   - Acceptance signal: leak-safe probe shows `pplx-next-auth-session` length > 0 AND the page is on `*.perplexity.ai` in a signed-in state.
   - Validation: page `text` shows the signed-in UI; cookie NAMES include `cf_clearance`/session cookies (names only, no values).
   - Acceptance evidence: token length + cookie names recorded (never values); no screenshots with account info; within the 15-min budget.
   - Repair attempts: 0
   - Recovery note: if the redirect never completes, re-check the user approved (phone), and verify Google didn't land on a challenge/error page; resume by polling again or re-entering the email.

5. [pending] Acquire the pxcli token via `pxcli auth login` (with direct-injection fallback) and verify
   - Task ID: T005
   - Depends on: T004
   - Parallel group: G5
   - Risk: medium
   - Owned scope: a host socat forward, `pxcli auth login`, `pxcli config`/env for save_cookies, optional inline fallback script — no repo files
   - Not in scope: pxcli source changes
   - Spike candidate: none
   - Actions: Set `PERPLEXITY_SAVE_COOKIES=true` (or `pxcli config set save_cookies true`) in the shell that runs pxcli AND any fallback. PRIMARY: bridge the browser CDP to host-localhost using a host inline Python forwarder (host `socat` is absent): `host-localhost:<port> -> 172.17.0.2:<port>` where the chromium was launched with `--remote-debugging-address=0.0.0.0 --remote-debugging-port=<port>`; pre-check `curl http://localhost:<port>/json/version`, read the advertised `webSocketDebuggerUrl`, forward that exact host:port too; run `pxcli auth login --port <port>`. Confirm success + token.json (0600). FALLBACK (expected if any bridging step fails): read `localStorage['pplx-next-auth-session']` (length via leak-safe eval) and cookie name/value pairs (values via a leak-safe transform, never printed), transform to `dict[str,str]` (`{c['name']: c['value']}` — the raw CDP array breaks `load_token`), then run a one-off HOST command (same host/user so the machine-bound encryption matches) that imports `TokenManager` and calls `save_token(token, cookies)`, with the token passed via an ENV VAR (never argv/ps), nothing committed. Verify `pxcli auth status` (local) then `pxcli auth status --verify` (live).
   - Acceptance signal: `pxcli auth status --verify` exits 0 (live API check) and `token.json` exists with mode 0600.
   - Validation: `pxcli auth status` (local) shows a token; `--verify` does a live call; `ls -l ~/.config/perplexity-cli/token.json` shows `-rw-------`.
   - Acceptance evidence: auth status output, token.json existence + perms; no token values in logs.
   - Repair attempts: 0
   - Recovery note: if `auth login` times out (120s), the logged-in tab is likely not the first page target or the bridge is broken — fix the forward / tab order and rerun. If the ws-URL is unresolvable, switch to the direct-injection fallback (documented in Actions).

6. [pending] Clean up and produce the evidence report
   - Task ID: T006
   - Depends on: T005
   - Parallel group: G6
   - Risk: low
   - Owned scope: browser session teardown, temp profiles, git hygiene check
   - Not in scope: anything else
   - Spike candidate: none
   - Actions: Close the browser session and kill the spike browser + any forwards; remove temp profiles (container /tmp and host /tmp scratch) AND the skill's `events.jsonl` capture for the session (it records console + request URLs, which can contain account identifiers); re-verify `.env` integrity (both keys present) and `git check-ignore .env`; run `git status --short` and verify no token/cookie/email artifacts in the tree or staged; write the final evidence summary.
   - Acceptance signal: `git status --short` shows no `.env`, no token/cookie files, and only the intended committed plan/scripts; all browser processes are gone.
   - Validation: `pgrep` for the spike browser/socats returns nothing; `git check-ignore .env` passes.
   - Acceptance evidence: git status output; process list; final report.
   - Repair attempts: 0
   - Recovery note: if any credential-bearing file shows in `git status`, stage nothing and remove/ignore it before any commit; do not commit credentials.

## Verification Strategy
- Stage gates (cheapest first): each task's acceptance signal is a direct command/probe (T001 DOM poll; T002 check-ignore; T003 page text; T004 localStorage eval; T005 auth status --verify; T006 git status). No build/lint applies (no committed code changes; the optional fallback is inline `python -c`).
- Live verification: T004 (localStorage token) then T005 (`pxcli auth status --verify` live API call) are the authoritative "token works" checks.
- Environment-sensitive: T001/T003/T004 depend on live Cloudflare + Google behaviour and the user's phone approval — they are inherently interactive and gated; failures at T001 are a decision point, not a repair loop.
- There is no repository-wide gate to run for this operational plan beyond T006's hygiene check, since it changes no source/analysers.

## Risks And Recovery
- R1 (high): Cloudflare blocks ALL automated browsers from the container IP (the webgl-disabled browser is PROVEN blocked; the webgl-enabled one is the T001 spike). If T001 = BLOCK: STOP, report evidence, and the user chooses a fallback (e.g. log in from their own host browser and import the token via the same T005 path, or solve the challenge in a way they can interact with).
- R2 (high): Google rejects the sign-in from the container IP/browser ("unusual traffic" / "This browser or app may not be secure"). Mitigation: the plan stops at the T003 gate and reports; the user decides (approve from a trusted device / use their own browser).
- R3 (medium): `pxcli auth login` CDP bridging fails (host-localhost constraint, ws-URL advertises the container IP). Mitigation: documented direct-injection fallback (T005) using the CLI's own TokenManager so encryption matches.
- R4 (medium): token extraction without `save_cookies` loses Cloudflare cookies -> later CLI calls may hit Cloudflare. Mitigation: enable save_cookies before T005 (A4).
- R5 (low): token.json machine-binding means it must be written on the host/user that will use pxcli. Mitigation: T005 runs on the host as the current user (matches where pxcli runs).
- R6 (low): secrets leak into logs/git. Mitigation: never echo the email/token; T006 hygiene gate; `.env` gitignored.
- Rollback: this plan is operational — nothing is modified in the repo except possibly `.env` (append-only, gitignored) and the plan doc. Rolling back = remove the appended line and delete token.json (`pxcli auth logout`).

## Critique Resolution
| Finding | Severity | Resolution | Evidence |
|---|---|---|---|
| T001/T003/T004/T005 had no driver for the custom webgl browser (csm-browse cannot launch without --disable-webgl; verbs only attach to csm-browse sessions) | Blocker | T001 now specifies an inline gitignored driver via chrome-remote-interface (already in the skill's node_modules) and a full reproducible in-container launch (user 1000, DISPLAY :0, session HOME/XDG dirs, full flag list); the validated launch recipe is a T001 deliverable reused by T003 | constants.mjs:40; ensure-browser.mjs no flag overrides; critique #1 |
| T005 "host socat" bridge cannot run — socat absent on the host | Blocker | Bridging rewritten: chromium binds 0.0.0.0 (`--remote-debugging-address=0.0.0.0`) reachable at 172.17.0.2:<port>; a host inline Python forwarder (host-localhost:<port> -> 172.17.0.2:<port>) replaces socat; direct-injection fallback promoted as expected-path alternative | verified `which socat` -> not found on host; critique #2 |
| ws-URL premise wrong (Chrome advertises ws://localhost:<internal>; pxcli doesn't rewrite) | Major | T005 adds a pre-check: curl the bridged /json, read the advertised webSocketDebuggerUrl, forward that exact host:port; failure routes to fallback | ensure-browser.mjs:156,224; oauth_handler.py:71; critique #3 |
| Fallback cookie shape (cookies verb returns CDP array; TokenManager needs dict[str,str]) | Major | Specified `{c['name']: c['value']}` transform + token handoff via env var / 0600 temp file (never argv), run on the host as the same user | token_manager.py:310-314; critique #4 |
| Credential leaks into transcripts (type echoes text; cookies/eval print values) | Major | Leak-safe eval expressions (length/boolean), name-only cookie processing, no screenshots while the email field is filled, T006 sweeps events.jsonl | input.mjs:75; log.mjs:190; dom.mjs:51; critique #5 |
| T001/T005 flag list incomplete | Major | Full flag set specified (incl. --remote-debugging-address=0.0.0.0, --password-store=basic, --disable-dev-shm-usage, --ozone-platform-hint=auto, --enable-software-rasterization) | constants.mjs:30-42; critique #6 |
| T004 deadlock risk (no timeout; sweep kills idle sessions) | Major | Bounded ~15 min approval budget with terminal STOP-and-report; fixed single session id across T003-T005 with no other-sid ensure/cleanup-stale | sweep.mjs:42-51; critique #7 |
| .env integrity (SAFETY_API_KEY could be corrupted) | Major | T002/T006 now verify SAFETY_API_KEY still present/unmodified after the append | .env verified newline-terminated; critique #8 |

## Progress Journal
| Timestamp | Cycle | Transition | Tasks | Evidence/result | Next state |
|---|---|---|---|---|---|
| 2026-08-06 | 0 | INTAKE | — | Ask = operational auth-flow plan: csm-browse Google login (phone approval) -> pxcli token; user cannot interact with the browser, will approve on phone | DISCOVER |
| 2026-08-06 | 0 | DISCOVER/RESEARCH | — | csm-browse skill loaded + verified; isolated browser PROVEN Cloudflare-blocked (webgl disabled, ~90s, reload); pxcli auth flow mapped (CDP localhost:9222, pplx-next-auth-session, encrypted token.json, save_cookies off); .env already gitignored, no dotenv dep; Google approval flow confirmed feasible in principle | DRAFT |
| 2026-08-06 | 0 | DRAFT | — | 6-stage gated plan written (feasibility spike -> credentials -> initiate -> approve -> extract -> cleanup) | CRITIQUE |
| 2026-08-06 | 0 | CRITIQUE | — | Independent critique: 2 blockers (no webgl-browser driver; host socat absent) + 6 majors (ws-URL premise, cookie shape, credential leaks, flag list, T004 deadlock, .env integrity) | REMEDIATE |
| 2026-08-06 | 0 | REMEDIATE | — | All 8 findings resolved in-plan: explicit CDP driver (chrome-remote-interface), host Python forwarder replaces socat, ws-URL pre-check, dict cookie transform + env token handoff, leak-safe probes, full flag list, 15-min approval budget + fixed sid, .env integrity checks | VERIFY |
| 2026-08-06 | 0 | VERIFY | — | Primary agent approved: AC1-AC6 map to T001-T006; gates + acceptance signals runnable; credential safety (gitignored .env, leak-safe verbs, host-bound encryption) enforced; T001 BLOCK-gate + fallback documented | SAVED |

## Completion Review
(filled by csm-build when all criteria are verified)
