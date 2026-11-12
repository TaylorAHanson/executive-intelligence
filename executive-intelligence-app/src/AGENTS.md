# AGENTS.md — Frontend (React SPA)

Read `../AGENTS.md` first. This file covers conventions inside `src/`.

React 19 + TypeScript + Vite, styled with Tailwind. Icons are `lucide-react`,
routing is `react-router-dom`, server state is TanStack Query, charts are
`recharts`.

| Path | What it is |
| --- | --- |
| `sections.ts` | The dashboard registry: drives routes, header nav, landing tiles, agent context. |
| `providers/` | `AppProviders` (query client, session, agent tray) and their hooks, `useSession` and `useAgentTray`. |
| `hooks/` | `useDashboardQuery` (widget data) and `useFilters` (filters in the URL). |
| `components/dashboard/` | The dashboard toolkit; import from `components/dashboard`. |
| `components/story/` | The briefing toolkit (chapters, so-whats, recommendations); import from `components/story`. |
| `pages/` | `LandingPage`, `NotFoundPage`, and one page (or folder, like `customers/`) per section. |
| `brand.ts` | App title and chart colors (recharts cannot read Tailwind classes). |

## Talking to the backend

**Always relative `/api/...` paths.** `api.ts` sets `const API_BASE = '/api'`.
In dev, Vite proxies that to `127.0.0.1:8010` (`vite.config.ts`); in production
FastAPI serves this bundle itself, so the same path resolves against the app's
own origin. Never introduce a hardcoded host or port.

This matters more than it looks. The same built assets get promoted from dev to
prod, so a URL baked in at build time is wrong everywhere except where it was
built. Anything that needs to differ per environment comes from the server at
runtime — which is how `SessionProvider` gets the environment label for the tab title.

**Add typed helpers to `api.ts`** rather than scattering raw `fetch` calls
through components. One place to change when a route moves, one place where
error handling is consistent.

## No secrets, ever

No API keys, tokens, or connection strings in `src/` — not in code, not in
`localStorage`, not in a `VITE_`-prefixed variable. Everything here ships to the
browser and is readable by anyone who opens devtools.

The user's Databricks token never reaches the frontend. The Apps proxy hands it
to the backend, and the backend keeps it. The browser doesn't send it either —
it just calls `/api/...` on its own origin and the proxy attaches identity on
the way through.

If a feature needs a credential, it needs a backend endpoint.

## Identity

The browser has no way to know who is signed in — the proxy authenticates the
request and tells the *backend*, not the page. So the SPA asks `/api/user/me`
rather than trying to decode anything client-side. `SessionProvider` loads it on
mount; read it anywhere with `useSession()`.

`on_behalf_of: false` means the backend is acting as a developer's CLI login
rather than through a real forwarded token. `Layout` badges that as `(local)` so
a laptop session is never mistaken for real per-user governance.

The same goes for invented data: `/api/health` reports `synthetic_data`
(`SYNTHETIC_DATA`, true unless set to `false`), and `Layout` shows a "Synthetic
data" badge while it is true, so a screenshot cannot pass for real figures.

## Errors belong on screen

`api.ts` throws `ApiError` carrying the backend's `detail` message, and
`AgentTray` renders it. Follow that pattern: a caught-and-swallowed error looks
exactly like a hung button, and the user has no way to tell the difference
between "still loading", "no results", and "this broke".

Show the backend's message rather than a generic one. FastAPI's `detail` is
written to be read — "No SQL warehouse configured" tells someone what to fix,
where "Request failed" does not.

Loads that only decorate the page should fail quietly instead: `SessionProvider`
tolerates a failed `/api/health` and renders without the environment badge,
because a missing label is not worth a blank screen.

Widgets get this for free from `WidgetState`, which shows the backend's message,
a Retry button, and, when `ApiError.sessionExpired` is set, a Reload button
instead (an expired Apps sign-in only recovers on reload). The query client does
not retry 4xx responses or expired sessions, which fail the same way every time.

## Incomplete data belongs on screen too

The backend's `run_query` returns `truncated`, `returned_rows`, and `total_rows`.
When `truncated` is true, the user is looking at part of the answer, and a table
of rows gives them no way to tell. `WidgetState` renders a banner for it under
every widget; anything that shows query results outside a widget must do the same.

Never compute a total in the browser by reducing over `rows`. Those rows are a
page, not the result set, so the number will look right and be wrong. Ask the
backend for the aggregate instead. `DataTable` sorts in the browser, which is
fine for display; a "top N" is ranked and limited in SQL.

## Adding a dashboard

A dashboard is a section in `sections.ts`, a page, its backend endpoints, and
the contract views it reads. `pages/ExecutiveInsightsPage.tsx` is the reference;
copy it.

1. **Data.** The views it reads must be in `../../data/contract.md` (and in
   `DATA_OBJECTS` in `server/config/settings.py`). Add any new ones there first.
2. **Backend.** `server/queries/<section>.py` and `server/routes/dashboards/<section>.py`,
   registered in `server/main.py` at `/api/dashboards/<section>`. See "Adding a
   dashboard endpoint" in `../server/AGENTS.md`.
3. **Agent context.** An id in `agentContexts.ts` and a matching `AppContext` in
   the agent's `agent/contexts.py` (a test fails if they drift). An id the agent
   does not know falls back to its general context.
4. **Registry.** An entry in `sections.ts`: `path`, `label`, `icon`,
   `agentContext`, `suggestedQuestions`, and `component: lazy(() => import(...))`.
   The route, the nav link, the landing tile, and the tray context follow from
   the entry.
5. **Page.** Render `DashboardPage` with the section id, `useFilters(DEFAULTS)`
   with `DEFAULTS` defined outside the component, and widgets fed by
   `useDashboardQuery('/<section>/<widget>', filters.values)`.

Widgets lay out on a 12-column grid by `span` (3, 4, 6, 8, 12). The toolkit:

| Component | For |
| --- | --- |
| `KpiCard` | One number from a one-row query, with a delta against `previous` and an optional sparkline. Several cards can share one query. |
| `ChartCard` | `line`, `area`, `bar`, `stacked-bar`. Wide rows via `series`, or long rows via `pivot`. Lines fit the y axis to the data; bars start at zero. |
| `DataTable` | Sortable columns with formats or custom `render`; shows `rowCap` rows, then "Show all". |
| `FilterBar` | Rendered by `DashboardPage` from `FilterDef`s: `daterange` (months), `select`, `multiselect`, `search`. |
| `WidgetCard`, `WidgetState` | The frame and the loading/error/empty/truncated states, for a custom widget. |
| `AskAboutButton` | Any widget's `askAbout` prop adds one. |

Values format through `formatValue` (`currencyCompact`, `percent` for fractions,
`month`, ...). Do not format numbers by hand.

**Filters live in the URL** (`?from=2026-01&regions=Europe,India`), so a filtered
view is a shareable link and survives a reload. A value equal to its default is
left out of the URL. Multi-select values are comma-separated, and the backend
reads them with `list_filter`.

### Briefings

Customer Intelligence (`pages/customers/`) is a briefing rather than a grid of
widgets: one scrolling page that argues cause to effect in four chapters (Know,
Measure, Anticipate, Act), for readers who will not operate filters. Build one
from `components/story`:

| Component | For |
| --- | --- |
| `StoryPage` | The shell: eyebrow, headline, the single "Ask" action, a sticky chapter nav that tracks scrolling, and the provenance footer. |
| `Chapter` | A chapter, opened by its one-sentence `soWhat`. |
| `Figure`, `FigureSkeleton` | One number set in type, with its comparison in words and whether that is good or bad news. |
| `Recommendation` | Because, Which means, So we; the owner; evidence behind a disclosure. |
| `Sparkline`, `Rich` | A trend without axes; prose with `**bold**` figures. |
| `useBriefing(scope)` | The insight records for `portfolio` or one account (`/customers/briefing?scope=`), split into headline, so-whats, and actions. |

The rules a briefing keeps:

- **The sentences are data.** Headline, so-whats, and recommendations come from
  insight records (`v_insights`), not from strings in the page, so whatever
  writes them (templates today, the signal loop later) changes the story without
  a deploy. The page writes only labels and captions.
- **Show where the sentences came from.** `StoryPage`'s `provenance` names what
  wrote the records and when; keep it.
- **No controls.** No filters, toggles, or settings; the period is fixed and
  said in words. The only action is asking the agent. A detail the reader may
  want goes behind a `<details>` disclosure or a link to the account page.
- **Format money with `money` from `components/story`**, which matches the
  generator's rounding in `data/insights.py`, so a figure in a sentence and the
  same figure in a chart read the same.

A section with sub-pages registers once in `sections.ts`; `App.tsx` mounts it at
`path/*` and the page declares its own nested `<Routes>`
(`CustomerIntelligencePage.tsx`). The tray context covers every sub-page.

## Adding a page

Routes are generated in `App.tsx` from `sections.ts`, with `LandingPage` at `/`
and `NotFoundPage` for everything else. `Layout` sits outside the routes so the
header and tray don't remount on navigation. A page that is not a dashboard
gets its own `<Route>` in `App.tsx` and, if it is about the app rather than the
data, an item in `components/AccountMenu.tsx` (the menu under the user's
initials) instead of a header tab; `ReleaseNotesPage` is the example. Pages live
in `pages/`, reusable pieces in `components/`.

**Use a normal browser router, not a hash router.** Deep links and hard refreshes
already work, and it is worth knowing why, because the reason lives in a file you
would never think to look at. When the browser requests `/reports/42`, that path
doesn't exist on disk — the *backend* answers it. `server/main.py` has a
catch-all that serves `index.html` for any non-`/api` path, so the SPA loads and
the router reads the URL client-side.

Two consequences of that arrangement:

- **Keep every API path under `/api`.** That prefix is the only thing separating
  a real endpoint from a client route. A backend route added outside it becomes
  unreachable the moment the catch-all is consulted.
- **A 404 for a bad client route is the router's job.** The backend returns
  `index.html` for anything it doesn't recognize, so an unknown path reaches the
  router rather than the browser's error page. The `*` route renders
  `NotFoundPage`; keep it last.

### Pages and the agent tray

The tray lives in `Layout`, outside the routes, so a conversation survives
navigation, and it keeps one conversation per context. `AgentTrayProvider` reads
the route: on a section's path the tray uses the section's `agentContext` and
shows it as a label instead of the picker, so the agent always knows which
dashboard a question came from. Elsewhere (the landing page) the user picks.

Open the tray from anywhere with `useAgentTray()`: `open()` keeps the draft,
`ask(question)` puts a question in the input, ready to send. Inside a
`DashboardPage`, `AskAboutButton` and the suggested questions append the active
filters in words, so the agent answers for the slice on screen.

Agent replies are markdown (GitHub-flavored, so tables work) rendered by
`components/Markdown.tsx`, which is lazy-loaded and ignores raw HTML; style new
elements there. The user drags the tray's left edge to resize it (arrow keys
when focused, double-click to reset); the width is kept in `localStorage`.

## Styling

Tailwind utilities, configured in `tailwind.config.js`, which holds the
palette: `brand` (plus `bright` and `dark`), `accent` (for badges and warnings
only), `canvas`, `line`, and `ink`. The brand colors, app name, assistant name,
and logo come from `../brand.config.ts`, which a deployment overrides from the
gitignored `branding/` folder (see "Branding" in the app README). Use the
Tailwind names rather than sprinkling hex values through components; where a
component needs a value (recharts, SVG), import it from `brand.ts`.

## Before you finish

```bash
npm run lint
npm run build    # type-checks via `tsc -b` — this is the real gate
```

`npm run dev` will not surface every type error. `npm run build` will, and it is
also what has to succeed before you can deploy.
