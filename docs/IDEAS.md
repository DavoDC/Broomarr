# Ideas & Future Work

Single source of truth for all pending work in this repo. Settled decisions and completed features -> `docs/HISTORY.md`.

---

## Current Focus

**Broomarr is ready for testing against the real library, in dry-run/flag/hold/cancel mode - not for a real deletion yet.** The test suite is green. The core safety invariants (hold period, cap-abort-not-truncate, canary-first, re-verify-before-delete) are built and tested, and none of the open audit findings below block read-only or hold-queue use: the destructive-confirm and blocking-GUI-action findings are UX problems on a control that still fails safe, and the rest are cosmetic or test-coverage gaps. This is the next step before further development, and it costs nothing to do now - run scans, flag items, watch them sit in the hold queue, cancel them, and record what breaks here.

**The protected-media exclusion list does not exist yet**, so a confirm
screen with no exclusion support can surface a protected title as a normal
candidate, survived only by the human reading the hold queue and the
week-long hold. That is the next thing worth building, before the first
real removal against the live library if practical - see "Protected-media
exclusion list" below.

---

**Tailscale access for a friend, prerequisites before giving it out.** David wants to give a friend access to the Broomarr GUI over a mesh VPN once he has tested it himself and confirmed the app works well - "pretty private but a bit public," in his words, since the friend's device becomes a peer on a private tailnet rather than a stranger on the open internet, but it is still a second person who did not write the code getting a browser pointed at the only tool in the house that holds a delete path. `gui/main.py:473` calls `ui.run(title="Broomarr", host="localhost", port=config.PORT, ...)` and `gui/config.py:20` hardcodes `PORT = 8472`, so the GUI is not reachable from any other device today, mesh or otherwise. Its entire access-control story, right now, is "nothing can connect" - and that single control is the one the friend's access proposal removes.

**The network layer is not enough on its own, and this is not a close call.** There is a directly reusable precedent for the network side, from a private household-infrastructure project not detailed in this public repo: this same friend was already onboarded to this same tailnet for a different set of admin tools, using a device-tag grant scoped to one host on an explicit port list and nothing else, a reusable time-limited auth key revoked the same day he finished adding his device, and node-key expiry disabled on the tagged device so it does not silently drop. He is almost certainly already a tagged device from that work, so the correct step is adding Broomarr's port to his *existing* grant rule rather than issuing a fresh key or inventing a new tag. But three properties of that precedent argue directly for application auth rather than against it. First, every one of those admin tools has its own login page, and the same rollout deliberately went further and closed their remaining local-address exemptions so a login is demanded from every address including the loopback - the household standard set there is network gate *plus* app gate, and Broomarr with no auth would be the only service on that tailnet reachable without a credential while also being the only one that deletes files. Second, the grant is a hand-edited policy document that has already been rewritten more than once; a one-line broadening is always one edit away, and the whole point of the tag-scoping was to avoid single points of failure, so leaning on it as the *only* gate reintroduces exactly what it was built to remove. Third, and most decisive: a tagged device is a device, not a person. That node carries no user account, has expiry disabled, and is permanently enrolled - so network identity answers "which machine" and can never answer "who is at the keyboard." Anyone with that laptop, or anything running on it, inherits the grant silently. **Broomarr needs its own authentication before its bind address changes, and the two layers are complementary rather than either/or.**

**Right-sized auth: a session-cookie login gate with two named accounts, not HTTP Basic and not a single anonymous shared password.** `gui/requirements.txt` pins `nicegui>=2.0`, and `grep -rin "auth\|password\|login\|session" gui/*.py src/*.py` returns nothing today, so this is greenfield. Two shapes are realistic. HTTP Basic Auth via a Starlette middleware is the smaller diff and needs no session state, but it is the wrong choice here for a specific reason: a browser cannot cleanly log out of Basic, and, more importantly, whether the browser attaches cached Basic credentials to NiceGUI's WebSocket upgrade is browser-dependent and unspecified - a hand-rolled ASGI gate in front of a socket-driven framework is precisely the kind of thing that breaks quietly on a library upgrade and fails *open*. The recommendation is therefore NiceGUI's own documented pattern: `ui.run(storage_secret=...)` plus `app.storage.user` for the session, a `/login` page, and a `BaseHTTPMiddleware` that redirects every request without a valid session to it, allowlisting only `/login` and NiceGUI's own static-asset prefix. It is maintained upstream, it survives NiceGUI upgrades, and it gives a logout and a place to hang a failed-attempt delay. **Two accounts, not one shared secret**, because the scope question below has to be expressible in the auth model rather than bolted on afterwards, and because separate credentials restore per-person attribution - the same reason the earlier onboarding tagged the friend's device instead of leaving him on shared admin logins. This is still nothing like an identity provider: it is a `gui_users` object in `config.json` mapping a name to a password hash and a role (`"admin"` or `"viewer"`), with the passwords handed over out of band and no recovery path by construction, exactly as David asked. Hash with `hashlib.pbkdf2_hmac` and compare with `hmac.compare_digest` (both stdlib, no new dependency); a `scripts/set-gui-password.py` helper generates the hash so a plaintext password is never typed into the file. Be honest about what the hash buys, though - `config/config.json` already holds plaintext Sonarr, Tautulli and Radarr API keys, so hashing is worth its ten lines but is not load-bearing, and the real protection is that the file is gitignored (`.gitignore` line 2, the "Real credentials" block) with a placeholder in `config/config.example.json`. Note `src/broomarr.py:46-67`'s `load_config()` ignores unknown keys, so new keys need no loader change; keep every one of them out of `src/`, which stays stdlib-only and GUI-free by invariant.

**The friend gets view-only, and the gate belongs in the handlers, not just in the markup.** Recommend the friend be a `viewer`: Dashboard, TV Shows, Movies, Blocked, plus read access to the Hold Queue and History so he can see what is pending and what happened, and no ability to flag, cancel or remove. Three reasons, in order of weight. The human reviewing the shortlist *is* the safety mechanism in this design, and widening that role to someone who has no stake in the library and no way to judge a false positive weakens the mechanism rather than sharing its load. The execute path is not ready for two hands on it: `do_execute()` (`gui/main.py:351-381`) has no re-entrancy guard, and the separate finding below that every long action blocks the event loop for *all* connected clients means a second user clicking Re-scan freezes David's session for minutes with no spinner and an enabled button inviting a second click. And the typed-REMOVE confirm (`gui/main.py:338-339`) is a bare unlabeled `ui.input` whose instruction vanishes on first keystroke and which silently ignores a trailing space - a first-time user is exactly who that fails worst. Implement the role check *inside* `on_flag()`, both `do_cancel()` closures and `do_execute()`, not only by omitting the buttons, and have `_build_hold()`/`_build_history()` render a read-only variant for a viewer. Also record the acting account in `state/reclaim-history.json` when a removal executes - with two accounts, an unattributed history is a regression.

**Binding: keep the app on loopback and put `tailscale serve` in front of it, rather than binding to the tailnet address.** `host` and `port` should both become config-driven (`gui_host`, defaulting to `"127.0.0.1"`, and `gui_port`, defaulting to `8472`) so the deployed value is a config edit and never a code edit, and `0.0.0.0` must never be the value - that would also publish the app to every device on the home LAN, which is a strictly larger audience than the tailnet and is not what anyone asked for. The better arrangement is that the listener never moves off loopback at all: `tailscale serve` reverse-proxies a tailnet-only HTTPS endpoint to `http://127.0.0.1:8472`, so the app has no routable socket, the connection is terminated by Tailscale, and the session cookie can be marked `Secure`. This corrects the earlier draft's line that a certificate is irrelevant here - it is true that WireGuard already encrypts peer traffic so TLS adds nothing for confidentiality, but once there is a session cookie, a real certificate is what lets it be `Secure`/`HttpOnly`/`SameSite=Lax`, and `tailscale serve` supplies one for free. **`tailscale funnel` must never be used on this app** - it is one subcommand away from `serve` and it publishes to the open internet, which for a tool with a delete path is the single highest-consequence mistake available anywhere in this plan. If `serve` turns out to be inconvenient, the fallback is binding `gui_host` to the machine's own tailnet address, never to all interfaces.

**Order matters because the verification has to be a negative test, not a green screen.** Nothing about a rendered login form proves a route is protected - a browser-rendered form and an unprotected page look identical in a markup check, which is a mistake this household has already made once. So the acceptance test for the auth work is a script that sends credential-free requests to the root, to each page route and to NiceGUI's internal endpoints and asserts a redirect or a 401 from every one, run before any grant is written. Relatedly, `Queue._load()`'s unguarded `json.load()` (see the test-gap finding below) becomes a second person's problem rather than only David's once someone else can load the page, since a truncated `state/reclaim-queue.json` takes down every tab at build time with a raw traceback.

**(a) To implement in this repo, in order, before any tailnet grant exists:**
1. `gui/auth.py` (new): `hash_password()`/`verify_password()` on `hashlib.pbkdf2_hmac` + `hmac.compare_digest`, `current_user()` reading `app.storage.user`, and a `require_login` `BaseHTTPMiddleware` allowlisting only `/login` and NiceGUI's static prefix. Add a `@ui.page("/login")` with a short fixed delay on failure and a single generic "incorrect" message.
2. `config/config.example.json` + README: add `gui_users` (name -> `{"password_hash": "...", "role": "admin"|"viewer"}`), `gui_storage_secret`, `gui_host` (default `"127.0.0.1"`), `gui_port` (default `8472`), all with placeholders. `scripts/set-gui-password.py` prints a hash for pasting. Never log any of these values.
3. `gui/config.py`: read `gui_host`/`gui_port` from config with the defaults above instead of the hardcoded `PORT`; `gui/main.py:472-475`'s `run()` passes them plus `storage_secret` to `ui.run()`.
4. Role enforcement inside `on_flag()` (`gui/main.py:158-162`), both `do_cancel()` closures (`297-303`, `317-323`) and `do_execute()` (`351-381`), plus read-only rendering of `_build_hold()`/`_build_history()` for a viewer, plus the acting account recorded into the history record.
5. Execute-path re-entrancy guard and the event-loop fix from the audit findings below: `run.io_bound` (or a thread offload) for `run_scan()`, `check_health()` and `reclaim.execute()`, a disabled button and spinner for the duration, and a module-level lock so a second `do_execute()` cannot start while one is running.
6. Accessibility fix on the destructive confirm: a real label that persists, `.strip()`-tolerant matching with an explicit "type REMOVE exactly" message on mismatch, a keyboard-reachable control rather than a disabled button, and visible focus rings.
7. `scripts/check-auth-enforced.py`: unauthenticated probe of every route including NiceGUI internals, asserting redirect-or-401 on all of them. Plus tests under `tests/` for `gui/auth.py` and for a viewer being refused at handler level, since nothing under `gui/` is tested at all today.
8. Guard `Queue._load()` against a corrupt or truncated state file so one bad JSON file cannot break the page for whoever opens it.

**(b) Manual steps and decisions for David, outside this repo:**
1. Confirm the view-only recommendation above, or overrule it deliberately and record why here.
2. Generate the two password hashes, fill `config/config.json`, and generate a long random `gui_storage_secret`.
3. Bring up `tailscale serve` pointing at the loopback listener, and confirm the URL is tailnet-scoped. Never `tailscale funnel`.
4. Run the unauthenticated-probe script and read its output before going further.
5. Test it himself end to end from a device that has actually left the property, on mobile data with wifi off - the same standard the earlier rollout held itself to, rather than retyping an address on the desktop.
6. Log in as the *viewer* account from a second browser profile and confirm the removal controls are absent, not merely greyed out.
7. Only then, add this one port to the friend's existing device-tag grant in the admin console - one host, one port, nothing broader - and hand him the password over a channel separate from the link.
8. Re-check after a month that the grant is still that narrow, since policy files drift.

---

## Pending - Main Work

*(Ordered by priority. Quick wins go FIRST within each tier - small, unblocked items before large/blocked ones. Items that are blocked or depend on other items go below their prerequisite.)*

---

**Run reaper in dry-run mode against the real library, once, before the next planning round.** The source audit (`docs/ALTERNATIVES.md`, `docs/HISTORY.md` 2026-09-14) found that reaper is the first tool in the survey not disqualified on architecture: it reads Sonarr's episode list as its denominator, rejects `episodeCount`/`totalEpisodeCount` for Broomarr's own reasons, and its unknown-handling is enforced by the type system. The case for maintaining Broomarr now rests partly on an assumption nobody has tested - that reaper's shortlist would be worse than Broomarr's. It ships with `dry_run` on by default plus a host-level environment variable that must be set before any mutating call, so a read-only trial costs nothing but setup time. Run it, compare its shortlist against Broomarr's on the same library, and record the result here. If it is as good, the honest conclusion is that Broomarr's remaining value is exactness and legibility, not capability - which is a fine reason to keep it, but a different one from the reason currently written down.

---

**Surface the incomplete-series protection as a named reason in `explain()`.** reaper shows an operator "episodes are missing" as an explicit protection reason rather than leaving it implicit in the outcome. Broomarr has the same fact and the better version of it (enumerated, not counted) but does not always say so in as many words. Cheap, and it is the kind of thing that makes a shortlist trustworthy to read.

---

**FUTURE OPTION, NOT A DECISION: opt-in auto-delete, armed only after a demonstrated reliability bar.** This is recorded as a proposal under consideration, and it remains one: the human-confirmed hold queue that now exists is deliberately *not* this, and nothing in it arms anything. `CLAUDE.md`, `README.md` and `DevContext.md` no longer claim Broomarr never deletes - see `docs/HISTORY.md`'s GUI entry for the rewrite - but what they describe instead is the confirm-twice flow below, not this option. **The confirm flow is the better answer to the same friction and it costs no automation; auto-delete is only worth reconsidering if that turns out not to be enough.** One piece of this entry's own argument is already built: the History tab is the persisted per-run record that would make any future reliability streak evidence rather than recollection.

The case for opening it: the media is re-downloadable, so the cost of a wrong deletion is usually bandwidth and inconvenience rather than loss, and the manual step is the main friction in actually using the tool. The case against a blanket flip: re-downloadability is not uniform (out-of-print, unusual cuts, anything personal), a wrong deletion is typically noticed weeks later by the person who wanted to watch it, and a *systematic* fault removes fifty shows rather than one, which is expensive even at a low per-item cost. See `docs/ALTERNATIVES.md`, "Are these the right axes?", for the full reasoning.

That shape of risk points at a narrow, staged design rather than a `--delete` flag:

- **Soft delete, never hard.** The armed path unmonitors the series in Sonarr and moves its files to a holding location, or flags them for removal on a timer. Actual deletion happens after a hold long enough for someone to notice - a month, not a day. Nothing is armed that cannot be undone by moving files back.
- **Arm per scope, never globally.** A tag, a specific set of titles, or a single library at a time. The protected-media exclusion list below is a hard prerequisite, not a companion feature - there must be no way to arm before exclusions exist.
- **Caps that abort rather than truncate.** A run that exceeds N items or M bytes stops entirely and reports, rather than deleting the first N. Truncating lets sort order pick the victims.
- **Canary first.** Smallest item, alone, verified, before anything else in the run proceeds. A broken path mapping then costs one file. (This and the previous two are reaper's design, borrowed deliberately - see `docs/ALTERNATIVES.md`.)
- **Two independent switches.** An in-config arm flag and a host-level environment variable, so no single bug or bad config can arm the tool.

"Proven reliable enough to arm" should mean something checkable, not a feeling. A defensible bar: **thirty consecutive days of scheduled dry runs whose shortlists were reviewed, with zero entries a human rejected**, plus a persisted record of each run so the streak is evidence rather than recollection. One rejection resets the count. The streak should be per-scope, since a tool that is reliable on one library has demonstrated nothing about another. Note that this bar is itself a feature to build - run logging and shortlist-diffing between runs - and it is worth building regardless of whether auto-delete ever follows, because a shortlist that changes between runs for no reason is a bug nobody would currently see.

Ordering: this comes after the protected-media exclusion list lands, and after the hold queue has been used in anger for a while. The confirm flow is the better answer to the same friction and it costs no invariant; auto-delete is only worth considering if that turns out not to be enough.

---

**The Sonarr-Tautulli join is by lowercased title, not a stable ID, and two
shows sharing a title would merge their watch history.** `watch_index()` keys
its dict by `grandparent_title.strip().lower()`, and `scan()`/`verdict()`
look up `series["title"].lower()` against it - there is no `tvdbId` or
rating-key cross-check anywhere in the join. Two Sonarr entries with the
same title (a US/UK remake, a reboot with an unchanged name) would read
from the *same* merged bucket of watched episodes, so watching S01E01 of one
could count as watching S01E01 of the other. Not live today - a scan of the
current 197-series library found no duplicate titles - but it is a
structural gap, not a today's-data coincidence, and it gets more likely as
the library grows. Worth deciding whether to key on `tvdbId` (Sonarr has
it; Tautulli's episode history rows do not carry it directly, so it would
need a Sonarr title->tvdbId lookup merged in) or at minimum warn on a
duplicate title the way `_warn_if_watcher_unmatched` warns on a
watcher mismatch.

---

**Remote access, when the GUI needs to become reachable from outside the house: prefer a private mesh network over a port forward.** A mesh VPN such as Tailscale, or its self-hosted equivalent Headscale, binds the app to a private address shared only between enrolled devices. There is no open port for a scanner to find, and someone who is not already on the network cannot reach the login page at all, let alone probe it. The free tier covers a household-sized set of devices, and node sharing invites one specific person to one specific service without handing them the rest of the network. It also replaces the certificate problem: a mesh network encrypts the link without anyone generating a self-signed certificate that every client then has to be told to trust.

The reason to prefer this over a port forward is sharper for a tool like this one than for the popular self-hosted applications it sits alongside. **A hand-written app is a worse thing to expose than a widely used community one.** A popular open-source project has many users, a security contact, published advisories and outsiders who report bugs in it, so when it turns out to be vulnerable a fix usually exists and the task is to have applied it. A tool written by one person for one library has none of that: no one else is reviewing its session handling or its input parsing, no advisory will ever be published for it, and the first person to find a flaw in it will be the one exploiting it. "Keep it patched" is not a strategy for software with no upstream. Given that this particular app is the only entry point that will ever hold a delete path, the asymmetry is worth taking seriously: the worst case is not a leaked watch history, it is someone else driving the deletion.

The same argument generalises beyond this repo. Anything self-written and reachable from outside the house belongs behind the mesh network, and putting one service there is most of the work of putting all of them there, so it is worth doing once and reusing rather than deciding per app.

---

## Audit findings - architecture and UI review, 2026-09-14

*(A pre-ship review of the whole repo as it stands after the combined build pass, not just the new code. Every entry carries an explicit priority: HIGH is safety-relevant or architecturally load-bearing, MEDIUM is a real bug or meaningfully bad UX, LOW is polish and hygiene. Ordered HIGH first.)*

---

**[MEDIUM] The watcher-mismatch warning never reached either the GUI or the movie side.** `_warn_if_watcher_unmatched()` is called from exactly one place, `broomarr.scan()`. `movie_scan()` does not call it, `MovieLibrary` has no equivalent, and the GUI surfaces watcher matching only inside the on-demand "Run health check" panel that a user has to think to press. Two designs asked for more than that and neither was built: `docs/design/gui-design.md` line 117 specifies a full-width banner across every REVIEW tab when the watcher matches nobody, with the explicit reasoning that a GUI presenting "0 safe to remove" as a tidy empty state camouflages the failure better than a terminal does; `docs/design/reclaim-backend-design.md` line 120 specifies that `movie_watch_index()` must distinguish "Tautulli returned no movie history at all" and warn in the same shape. Both failures are fail-closed (everything blocks rather than passing), so this is not a wrong-delete risk, but it is a designed safety surface that was dropped without appearing in the disclosed scope-trim list in `docs/HISTORY.md`, which only names cosmetic omissions. The honest fix is a banner component in the GUI plus the movie-side warning, or a decision recorded here that both were dropped deliberately.

---

**[MEDIUM] Every long-running action blocks the GUI's event loop, with no loading state and nothing preventing a second click.** `do_rescan()` in `gui/main.py` calls `STORE.run_scan()` synchronously inside a NiceGUI click handler, and that is a full library scan: the bulk Sonarr list, the whole Tautulli history, then one `/api/v3/episode` call per surviving candidate. On a library of a couple of hundred series that is minutes during which the server answers nothing at all, for every connected client, while the Re-scan button stays enabled and un-spinnered so the natural response is to click it again. `check_health()` and `do_execute()` have the same shape, and for `do_execute()` a queued second click means a second `reclaim.execute()` run against items the first run already deleted, which lands straight on the 404 path in the first finding above. Wants `run.io_bound` (or an equivalent thread offload), a disabled button plus a spinner for the duration, and a guard against re-entry on the execute path specifically.

---

**[MEDIUM] The GUI reads as a NiceGUI scaffold with dark mode on, not as the Sonarr/Radarr/Overseerr-shaped interface the design asked for.** Setting aside the poster grid and the view toggle, which `docs/HISTORY.md` disclosed as a deliberate trim, several things that cost almost nothing are missing and their absence is what makes the page read as unfinished. The left nav has no active state at all, so there is no way to tell which of the six tabs you are looking at; there are no icons, no hover treatment, and no header bar above the content pane. Styling is ad-hoc inline hex strings assembled by `_card_style()` and `_badge()` rather than a small set of CSS variables, so the palette is restated at a dozen call sites and cannot be adjusted coherently. The REVIEW/RECLAIM split exists in the markup as one `border-top` on a group label, which is not enough to read as the deliberate mutate-versus-observe boundary the design makes it. The Hold Queue's "two physically separate lists" are two identically styled `ui.label` headers over identically styled rows, so the strongest safety affordance in the application looks like one list with two captions. `ui.dark_mode().enable()` in `index()` duplicates `dark=True` in `run()`. Contrast is mostly acceptable but the `#777` group labels on the `#161616` sidebar at 11px fall under 4.5:1. Polish rather than safety, but this is the surface a destructive action lives on and it currently does not look like one that was designed.

---

**[MEDIUM] The destructive confirmation has no accessible affordances.** The typed confirm in `_build_hold()` is a bare `ui.input(placeholder="Type REMOVE to enable")` with no label, so the only instruction disappears the moment a character is typed; the match is exact against `"REMOVE"`, so a trailing space or a lowercase attempt silently does nothing and the user gets no explanation; and the Remove button toggles from disabled to enabled with no announcement, while a disabled button is not focusable and not reachable by keyboard tabbing at all. There are no visible focus rings anywhere in the app. For the one control in the repo that deletes files, "you cannot tell why the button is not working" is the wrong failure mode even though it fails in the safe direction.

---

**[MEDIUM] README tells the reader there are no dependencies and then tells them to run the GUI.** The Setup section says "Python 3.8 or newer. No dependencies, standard library only," and the Running it section says to run `python -m gui.main` or `scripts\run-gui.bat`. `gui/requirements.txt` (`nicegui>=2.0`) is never mentioned in the README, and `scripts/run-gui.bat` checks only for `config/config.json` before invoking `python -m gui.main`, so a reader following the documentation exactly gets a `ModuleNotFoundError` with nothing pointing at the cause. The claim wants qualifying ("the CLI has no dependencies; the optional GUI needs `pip install -r gui/requirements.txt`"), and the launcher wants a friendlier failure when the import is missing. The README also never documents `hold_days`, `max_scan_age_days`, `max_items` or `max_bytes`, which exist only in `config/config.example.json`, even though they are the tunables that govern the delete path.

---

**[LOW] Test gaps worth closing, all of them cheap.** `CLAUDE.md` states that `broomarr.py` "never imports `reclaim`" as a named invariant and no test asserts it (`test_broomarr_module_issues_no_non_get_request` greps for `method=`, which is a different claim). There is no test that a `CANCELLED` item cannot be executed - the current behaviour is safe, since `is_due()` returns `False` for any non-`PENDING` state, but it surfaces as a `ReclaimError` reading "hold period has not elapsed", which is a misleading message for a cancelled item and nothing pins the behaviour down. Nothing under `gui/` is tested at all, including `data.flag()`, which is the function that assembles the evidence dict every interlock later reads. And `Queue._load()` calls `json.load()` unguarded, so a truncated or hand-edited `state/reclaim-queue.json` takes down every tab of the GUI at page build with a raw traceback; there is no test and no recovery path.

---

**[LOW] Dead and leftover code in `gui/`.** `_build_hold()` contains `"hold ends in %d day(s)" % int(remaining) + 1 if False else "hold ends in ~%d day(s)" % (remaining)`, an abandoned ternary with a permanently false condition that shipped as-is. `_build_dashboard()` computes `earliest = min(r["flagged_at"] for r in pending)` and never uses it. `_build_review_table()`'s `show_all_state` parameter is passed a fresh `[False]` literal by both callers, so the state it exists to preserve is discarded on every rebuild. `gui/config.py` defines `COVERS_CACHE_DIR` for a poster cache that was never built. `data.Data.flag()` has an `if kind == "tv": ... else: ...` whose two branches assign `service_id` identically. `reclaim_defaults_hold_days()` is a public-looking helper among underscore-prefixed siblings, defined below its own call site, doing a function-local import.

---

**[LOW] TV sizes round-trip through gigabytes before being stored as bytes.** `data.Data.flag()` stores `int(item["size_gb"] * 1e9)` for TV because `dry_run_report.evaluate()`'s item dict carries only `size_gb`, while the movie path stores the exact `item["size_bytes"]` that `_gather_movies()` kept. Those stored bytes are what interlock 4 sums against `max_bytes`, so the cap is being checked against a lossy number on one of the two sides. Adding `size_bytes` to `evaluate()`'s dict alongside `size_gb` makes the two paths identical and removes the asymmetry.

---

**[LOW] `gui/data.py` only imports successfully because `gui/main.py` happens to import `gui.config` first.** `gui/config.py` is what inserts `src/` onto `sys.path`, and `gui/data.py` does `import broomarr` at line 14, four lines before `from gui import config` at line 18. `gui/__init__.py` is empty, so `import gui.data` on its own (a test, a REPL, any future entry point) raises `ModuleNotFoundError`. Moving the path insertion into `gui/__init__.py`, or importing `gui.config` first in `data.py`, removes an ordering dependency that currently holds by luck. Relatedly, `gui/main.py`'s own docstring says to run `python gui/main.py`, which does not work - that puts `gui/` on the path rather than the repo root, so `from gui import config, data` fails. `CLAUDE.md` and the README both have the correct `python -m gui.main`.

---

**[LOW] Empty states do not distinguish which kind of empty they are.** `docs/design/gui-design.md` line 259 asks for exactly this: "nothing is safe to remove", "the scan has not been run" and "the watcher matches nobody so everything blocked" are three different states that all render as an empty list, and conflating them recreates the failure `_warn_if_watcher_unmatched()` exists to prevent in a prettier form. As built, `_build_review_table()` has two generic strings ("Nothing here yet - run a scan from the Dashboard" and "Nothing is safe to remove right now") and no third state, and neither carries a remedy button.

---

## Lower Priority / Future

*(Ordered by size - smaller/quicker first. These are not urgent but worth doing eventually.)*

---

**Protected-media exclusion list.** Some titles (a specific rewatch favourite, say) and some whole categories (anime as a category, for example) should never be surfaced as a deletion candidate at all, regardless of watch state - not "warn and let a human override," but excluded from `verdict()` before a candidate is ever produced. This wants two levels: an exact-title (or stable-ID) exclude list in `config.json`, and a category/genre-level exclude flag, since Sonarr exposes genre/tag metadata per series. Needs a decision on whether the category match is a hardcoded genre string or a configurable list, and whether exclusion is silent (title never appears anywhere) or shows up in `explain()` as "excluded, not evaluated" for transparency.

---

**GUI visual polish deferred from the build pass.** `gui/main.py` implements every safety-critical behaviour from `docs/design/gui-design.md` verbatim (the hold queue's two physically separate sections, the typed "REMOVE" confirmation, no execute control at all on a held item, Blocked staying read-only) but skips several purely cosmetic details for a later pass: a grid/table view toggle for Movies vs TV Shows, poster proxying with a `state/covers/` cache, the amber close-call band keyed to `MARGIN_DAYS_RISKY` (a plain badge stands in for it today), and tabular-numeral typography. None of these affect what can be flagged, held, or removed - see `docs/HISTORY.md`'s GUI entry.

---

**Exploratory: chat-bot confirmation flow as an alternative to browser + mesh VPN access.** The remote-access plan above (mesh VPN such as Tailscale) assumes a device can run a VPN client freely. Some devices only allow one active VPN profile system-wide, which could conflict with another VPN already in use on that device. If that constraint holds, a chat-bot interface (e.g. a messaging-platform bot) that sends a candidate list and accepts a reply as confirmation could substitute for reaching the web UI directly, without opening a port. This is speculative - the actual constraint needs verifying on the specific device before any design work, and it must not reduce the human-confirms-each-deletion invariant to a single blanket "yes." **This repo is public** - do not record who the approving household members are anywhere in it; a generic "approver" role in config is fine, specific people are not.

---

**Multiple watchers per show, not one named watcher.** `config.json` currently
takes a single `watcher` string matched case-insensitively. Households where
more than one person needs to have finished a show before it is safe to
remove would need the verdict to require all configured watchers, not just
one - matters for shared libraries, not solo ones. `Library.matches_watcher()`
is the single place the matching rule lives, so this change has one seam
rather than several.

---

**The substring watcher match is loose.** `matches_watcher()` is a
case-insensitive substring test, so a configured watcher of `sam` matches a
Tautulli friendly name of `samantha`. That is convenient and it is also a way
to silently consult the wrong person's history. Worth tightening to an exact
match with substring as an explicit fallback, or at least warning when the
configured value matches more than one friendly name.

---

## See Also

- `docs/HISTORY.md` - completed features, settled design decisions, parked ideas
