<!--
  User-facing release notes, shown in the app under the account menu > Release
  notes (src/releaseNotes.ts parses this file; tests/test_release_notes.py and
  ../deploy.sh fail if the top release and package.json "version" disagree).

  Conventions:
    * Newest release first. Add a new `## <semver> — <YYYY-MM-DD>` block on top.
      Bump per semver: major = breaking change or redesign, minor = new
      user-facing feature, patch = fixes and small tweaks. If the top entry is
      still unreleased work from the same batch, add to it instead of stacking.
    * Keep package.json "version" in sync with the top entry.
    * Group bullets under Added / Changed / Fixed. Omit groups you don't need.
    * Ship the notes in the same commit as the change. Nobody backfills these.
    * Write for the people using the app, not for reviewers.
    * One bullet per user-visible change. Merge bullets about the same thing.
    * Each bullet is a bold lead naming the change, then at most one short
      sentence (~25 words in total). Say what someone can now do and where
      (menu path, button name), not why it changed or how it was built.
    * No root causes, internal names, file or function names, or before/after
      narratives. Add a second sentence only when the reader must act.
    * Aim for a release that fits on one screen.
    * Skip entries for changes nobody using the app could notice (refactors, tests).
  This comment is an HTML comment, so it never renders in the app.
-->

# Release Notes

## 0.3.0 — 2026-11-13

### Added

- **Needs attention first.** Customer Intelligence now opens with the accounts at risk, soonest renewal first, and the share of revenue and renewing contracts they hold.
- **Since you last looked.** The briefing lists what moved since your last visit: newly at-risk accounts, commit, plan and device share.
- **Portfolio map.** A chart of all ten accounts by revenue against plan and change in device share. Click a bubble to open the account.
- **Plan-to-commit waterfall, coverage bar and renewal ladder.** See where the quarter lands, whether open deals could cover the gap, and which contracts end in the next year.
- **Account vitals and annotated revenue chart.** Each account page opens with its next contract end, plan, device share and quarter gap, and marks contract ends and risk signals on the revenue chart.
- **Copy summary and Print / PDF.** Share a briefing as text, or print it.
- **Ask why.** Each recommendation has a button that asks the assistant about it. Starter questions sit under each headline.

### Changed

- **Answers first.** Every chapter now opens with its takeaway, above the detail.
- **Accounts table.** At-risk accounts are listed first, with the reason, the quarter's gap to plan and days to renewal. Click a heading to sort.
- **Colors mean status.** Red, amber and green are now only used for status, not to tell chapters apart.
- **Tablets.** The assistant opens over the page instead of beside it, and the accounts become cards when space is tight.

## 0.2.0 — 2026-11-12

### Added

- **Account menu.** Click your initials at the top right to see who you're signed in as and open these release notes.
- **Release notes.** A dot on your initials means there's a release you haven't read yet.
- **Settings.** Admins choose each section's assistant instructions and data sources under the account menu > **Settings**, and can restore a section's defaults.

### Changed

- **The assistant answers with your own access.** It sees only the data you could query yourself, the same as the dashboards.

## 0.1.0 — 2026-11-11

### Added

- **Executive Insights.** Revenue, on-time delivery and design wins by period and region, with the top customers.
- **Customer Intelligence.** A briefing on the top 10 accounts: what they're focused on, how we're doing, where the quarter lands, and what to do. Each account has its own page.
- **Ask the assistant.** The **Ask** button at the top right opens a panel that answers questions about the dashboard you're on and remembers what you tell it.
