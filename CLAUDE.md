# CLAUDE.md

Guidance for working on this repo. Read this before editing the filter lists.

## What this repo is

Personal cosmetic-filter lists that declutter YouTube, in uBlock Origin / Adblock-Plus
filter syntax. They're consumed as **custom filters** in uBlock Origin (desktop) and in
Brave's *Content Filtering → Custom Filters* (desktop, Android, **iOS**).

| File             | Applies to        | Notes                                                    |
| ---------------- | ----------------- | -------------------------------------------------------- |
| `yt-desktop.txt` | `www.youtube.com` | Desktop web. Already on the new `lockup-view-model` DOM. |
| `yt-mobile.txt`  | `m.youtube.com`   | Mobile web — what iOS Safari/Brave load. Mostly legacy DOM; lockup is rolling out. |
| `inspect-dom.py` | tooling           | Renders YouTube's live DOM to find/verify selectors (see below). |

## Filter syntax used here

- `domain##selector` — **hide** every element matching the CSS selector (`display:none`). Plain, portable.
- `domain##selector:style(prop: val !important;)` — inject CSS instead of hiding (used for collapsing margins/heights). **Procedural — see iOS caveat.**
- `domain##selector:has(...)`, `:remove-attr(...)` — procedural operators. **Also iOS-limited.**
- `# ...` — comment.
- **Disable convention:** the author parks a rule by prefixing the selector with `DISABLE`/`DISABLED`
  (e.g. `##DISABLEytd-thumbnail`, `##DISABLEDshorts-video`). This mangles the selector so it matches
  nothing, keeping the original text for easy re-enabling. To re-enable, delete the prefix.

## Platform caveat — this is usually the real bug (Brave on iOS)

iOS forces every browser onto WebKit, and cosmetic filtering there is restricted:

- ✅ Plain `##selector` element-hiding works.
- ❌ **uBO procedural / action operators do NOT run on iOS:** `:style()`, `:has()`, `:has-text()`,
  `:remove-attr()`, `:upward()`. So every `:style()` line in `yt-mobile.txt` (margin/height
  collapsing) is a **no-op on iPhone** — hide rules fire, but leftover gaps remain.
- **Prefer plain hide rules for anything that must work on iOS.** Don't rely on `:style()` there.
- After editing on iOS Brave: paste rules into *Settings → Shields & privacy → Content Filtering →
  Custom Filters*, confirm **Shields are UP** on the site, then **force-quit & relaunch Brave**
  (iOS compiles filters at launch; there is no hot-reload).
- Desktop/Android Brave and uBlock Origin support the full syntax.

If a rule "doesn't work" on iOS, first prove cosmetic filtering is active at all with an obvious
plain rule — `m.youtube.com##ytm-pivot-bar-renderer` hides the bottom nav bar. If that doesn't
disappear, the problem is Brave-iOS config (Shields/restart/version), **not your selector**.

## Verified element reference (live DOM, May 2026)

Run `inspect-dom.py` to re-confirm — YouTube changes these.

| Surface (a video in the feed/search) | mobile `m.youtube.com` | desktop `www.youtube.com` |
| --- | --- | --- |
| Video card container | `ytm-video-with-context-renderer` (home grid wraps it in `ytm-rich-item-renderer`) | `ytd-rich-item-renderer`, `yt-lockup-view-model` |
| Video **thumbnail** | `a.media-item-thumbnail-container` (legacy), `.ytLockupViewModelContentImage`, `.yt-lockup-view-model__content-image`, `.yt-lockup-view-model-wiz__content-image` | `a.ytLockupViewModelContentImage`, `a.yt-lockup-view-model__content-image` |
| Creator **avatar** | `ytm-channel-thumbnail-with-link-renderer` (legacy), `.ytLockupMetadataViewModelAvatar`, `.yt-lockup-metadata-view-model__avatar`, `.yt-lockup-metadata-view-model-wiz__avatar` | `.ytLockupMetadataViewModelAvatar`, `.yt-lockup-metadata-view-model__avatar` |
| Title / metadata (keep visible) | `.details` / `.media-item-details` | `#meta`, `yt-content-metadata-view-model` |

**Lockup migration:** desktop is fully on `lockup-view-model`; mobile is mid-rollout (the served HTML
carries flags like `mweb_enable_lockup_view_model_*`). When mobile flips, `media-item-thumbnail-container`
and `ytm-channel-thumbnail-with-link-renderer` can disappear and the lockup/wiz classes appear. That's
why `yt-mobile.txt` lists **both** legacy selectors and lockup/wiz selectors — the rules survive the
switch. Keep doing this when adding new mobile rules.

## How to find a selector (the workflow I used)

The single most important rule: **YouTube is a JavaScript SPA. Do not guess class names or trust
`curl`/view-source** — the page source is just a loader plus a `ghost-*` skeleton; the real elements
and their class names exist only after client-side render.

1. **Render the real DOM with the target engine + UA.** `inspect-dom.py` launches headless Brave
   (Chromium) with an iPhone user-agent (so YouTube serves `m.youtube.com`) and drives it over the
   DevTools Protocol. (`--dump-dom` is avoided on purpose: YouTube's perpetual timers prevent
   Chromium's virtual-time budget from completing, so it hangs.)
2. **Use a populated page.** The logged-out **home** feed renders empty ("Your YouTube history is
   off"). Use a **search** page (`/results?search_query=...`) or a **watch** page — both render the
   same `ytm-video-with-context-renderer` items the home feed uses.
3. **Read the match count + ancestor chain:**
   ```sh
   python3 inspect-dom.py 'https://m.youtube.com/results?search_query=lofi' \
       'a.media-item-thumbnail-container' \
       'ytm-video-with-context-renderer ytm-channel-thumbnail-with-link-renderer'
   # add --desktop for www.youtube.com
   ```
   With no selectors it prints a summary (legacy-vs-lockup, thumbnail + avatar candidate counts).
   The ancestor `chain` is what tells you how to scope a rule.

## How I decided what to change (worked examples)

**1. "Thumbnail filter doesn't work on iPhone."**
`inspect-dom.py` matched `a.media-item-thumbnail-container` on **19/19** video items — the selector
was already correct. So the fix was *not* the CSS. The causes were (a) Brave-iOS only applies plain
rules and needs a relaunch, and (b) the upcoming lockup migration. I left the selector alone and
**added the lockup thumbnail selectors** for future-proofing. **Lesson: verify the selector against
the live DOM before changing it** — a rule that "doesn't work" is often an application/platform issue.

**2. "Creator avatar still shows."**
The avatar is `ytm-channel-thumbnail-with-link-renderer`. The old rule scoped it as
`.media-channel ytm-channel-thumbnail-with-link-renderer`, but the chain showed `.media-channel`
only wraps it on **search rows**; the **home feed** lays it out differently, so the rule missed the
page actually being browsed. The common ancestor across both surfaces is
`ytm-video-with-context-renderer`, so I re-scoped to that. I deliberately did **not** hide
`ytm-channel-thumbnail-with-link-renderer` globally, because that would also remove the watch-page
owner avatar (`ytm-slim-owner-renderer`), which isn't a feed thumbnail.

**General principle for scope:** pick the *narrowest* selector that (a) matches every surface you
browse (home feed + search + related) and (b) doesn't catch elements you want to keep. Verify both
properties with `inspect-dom.py` before committing.

## Testing a change

- Confirm a selector matches real items: `python3 inspect-dom.py <url> '<selector>'` (count > 0).
- Confirm it doesn't over-match: check the `chain` of `first`, and probe a page where the element
  should be *kept* (e.g. a `/watch` page) to be sure your scope excludes it.
- On iOS: re-paste into Custom Filters and force-quit/relaunch Brave (see caveat above).

Prereqs for the tool: Python 3 + a Chromium-based browser. Defaults to
`/Applications/Brave Browser.app`; override with `BRAVE_BIN=/path/to/browser`.
