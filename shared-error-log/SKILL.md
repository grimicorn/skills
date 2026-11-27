---
name: shared-error-log
description: >
  Library skill — not user-triggered. The single destination and append procedure
  for error logging across every skill and agent. One file,
  $OBSIDIAN_VAULT/Errors.md, one schema (date | source | item | note), with rows
  inserted above the ^errorTable anchor. Read this skill whenever a calling skill's
  instructions say to "log an error", "append to Errors", "log to the Errors table",
  or record a usage-limit / API / login / per-item failure. Supersedes the per-skill
  Errors tables, the shared Cross Posters/Errors.md, and shared-usage-limits Mode A's
  per-skill schema.
---

# Shared: Error Log

One error log for the whole system. Not triggered by users — referenced from
calling skills by path. Every skill and every agent writes failures **here**, never
to its own local Errors table.

- **File:** `$OBSIDIAN_VAULT/Errors.md`
- **Schema:** `| date | source | item | note |`
- **Anchor:** rows are inserted **above** the `^errorTable` block reference at the
  end of the file (the Overview doc links to `^errorTable`, so it must stay the last
  line and stay attached to the table).

```
| date | source | item | note |
| ---- | ------ | ---- | ---- |
^errorTable
```

---

## Anchor Rule (do not break this)

This is the rule that keeps `![[Errors#^errorTable]]` from silently rendering empty in
the Overview doc. It is stated here because this skill owns `Errors.md`; every other
skill that writes an anchored table follows the same rule.

An Obsidian block anchor binds to the table above it **only** when both hold:

1. The anchor sits on the line **immediately after** the table's last row — no blank
   line between the table and the anchor.
2. The line directly **below** the anchor is blank, **or** the anchor is the last line
   of the file.

If anything is jammed against the anchor from underneath — a heading, a `---`, a
sentence, another table — the anchor binds to nothing and the embed renders empty with
no error and no warning. Nothing in the pipeline catches this.

```
| ---- | ------ | ---- | ---- |
| July 1st, 2026 | concert-search | Bandsintown | site returned 503 |
^errorTable            <- flush under the last row
                       <- blank line, or nothing at all (EOF)
```

For `Errors.md` specifically:

- `^errorTable` **ends the file.** Never append anything below it — not a heading, not a
  note, not a trailing `---`. New rows go **above** it, inside the table.
- Never insert a blank line between the last row and the anchor. `log_error` maintains
  this automatically; hand-edits are where it breaks.
- The anchor's name is irrelevant to whether it binds. `^errorTable` and a random hex ID
  behave identically. An empty embed is always a placement bug, never a naming one.

---

## Column meaning

| Column   | What goes in it | Example |
|----------|-----------------|---------|
| `date`   | House format from `shared-env` — `May 8th, 2026` (month spelled out, ordinal day, 4-digit year, no time). Rows insert in run order, so top-to-bottom is already chronological; this is a table you scan, not sort. | `July 1st, 2026` |
| `source` | The skill that hit the error — its exact folder name. Agents use the literal `agent` (the repo name goes in `item`). | `concert-search`, `youtube-transcript`, `agent` |
| `item`   | What was being processed when it failed: the site / artist / video / repo / listing / slug. For an agent, the repo name. Use `-` when the failure isn't tied to one thing (setup, usage-limit, run-level). | `Bandsintown`, `dQw4w9WgXcQ`, `basin` |
| `note`   | The error itself, one short line. | `GitHub API unavailable`, `Bluesky not logged in — manual login required` |

`source` is a fixed identifier per caller — decide it once in the calling skill, don't
recompute it per row.

### Choosing `source` and `item`

- **`source` = the skill's folder name**, always (e.g. `bluesky-post`, `concert-search`).
  It stays stable across a rename because folder and source move together.
- **`item` = the single thing being processed** when it failed. For most skills the skill
  name already implies the *kind* of work, so `item` just names the instance (a slug, an
  artist, a URL, a video id).
- **Multi-target skills are the exception.** When one run legitimately spans several targets
  the folder name can't distinguish — e.g. `social-location-sync` touches Twitter, Hashnode,
  Dev.to, LinkedIn in a single run — put the target in `item` (the platform), not `source`.
  This is the *only* case where a platform/site name belongs in `item`; a single-platform
  poster like `bluesky-post` must not, because `source` already says which platform.
- **Agents** use `source: agent` with the repo in `item` (e.g. `basin`).

---

## Writing an error (insert above the `^errorTable` anchor)

The row goes **inside** the table, immediately after the last existing table row, so it
stays contiguous with the table and above the trailing `^errorTable` anchor. That is a
read-modify-write, not a bare append, so it is **not** atomic across processes on its own.
Concurrent scheduled skills on the always-on Mac can write at the same time, so `log_error`
takes a short `mkdir`-based lock (`macOS` has no `flock` binary) and writes via a temp file
plus `mv`. Do **not** remove the lock — without it, two simultaneous writers read the same
file and the second `mv` drops the first writer's row.

**Init (safe if the file is missing, safe under a race):**

```bash
FILE="$OBSIDIAN_VAULT/Errors.md"
mkdir -p "$OBSIDIAN_VAULT"
if [ ! -f "$FILE" ]; then
  # noclobber: if another run created it first, fail instead of truncating its rows
  ( set -o noclobber
    # anchor flush under the table and last in the file — see Anchor Rule above
    printf '| date | source | item | note |\n| ---- | ------ | ---- | ---- |\n^errorTable\n' > "$FILE"
  ) 2>/dev/null || true
fi
```

**Insert one row (above `^errorTable`):**

```bash
# shared-env date format (May 8th, 2026). Portable: BSD date (macOS) has no %-d,
# so take zero-padded %d and strip the leading zero. 11/12/13 always take -th.
fmt_date() {
  local mon day yr suf
  mon="$(date +%B)"; yr="$(date +%Y)"; day="$(date +%d)"; day="${day#0}"
  case "$day" in
    11|12|13) suf=th ;;
    *1) suf=st ;; *2) suf=nd ;; *3) suf=rd ;; *) suf=th ;;
  esac
  printf '%s %s%s, %s' "$mon" "$day" "$suf" "$yr"
}

log_error() {
  # usage: log_error "<source>" "<item>" "<note>"
  local FILE="$OBSIDIAN_VAULT/Errors.md"
  local LOCK="$OBSIDIAN_VAULT/.Errors.lock"
  local ts src item note row i
  ts="$(fmt_date)"
  # escape pipes and collapse newlines/tabs so a stray | or \n can't corrupt the table
  src="$(printf '%s' "$1"  | tr '\n\t' '  ' | sed 's/|/\\|/g')"
  item="$(printf '%s' "$2" | tr '\n\t' '  ' | sed 's/|/\\|/g')"
  note="$(printf '%s' "$3" | tr '\n\t' '  ' | sed 's/|/\\|/g')"
  [ -n "$item" ] || item='-'
  row="| $ts | $src | $item | $note |"

  # Portable lock (macOS has no flock binary): spin on mkdir, ~5s cap then best-effort.
  i=0
  until mkdir "$LOCK" 2>/dev/null; do
    i=$((i+1)); [ "$i" -gt 50 ] && break
    sleep 0.1
  done

  if grep -q '^|' "$FILE" 2>/dev/null; then
    # insert the row right after the last existing table row (keeps rows contiguous
    # and above the trailing ^errorTable anchor); temp file + atomic mv.
    # Pass the row via the environment (ENVIRON), NOT `awk -v`: -v reprocesses
    # backslash escapes and would strip the \| pipe-escaping back to raw |.
    ROW="$row" awk '
      { line[NR]=$0; if ($0 ~ /^\|/) last=NR }
      END { for (n=1;n<=NR;n++){ print line[n]; if (n==last) print ENVIRON["ROW"] } }
    ' "$FILE" > "$FILE.tmp" && mv "$FILE.tmp" "$FILE"
  else
    # no table yet (file missing/empty) — plain append
    printf '%s\n' "$row" >> "$FILE"
  fi

  rmdir "$LOCK" 2>/dev/null
}
```

Call it with the caller's fixed `source`:

```bash
log_error "concert-search" "Bandsintown" "site returned 503 — skipped"
```

That's it. No dedup, no sorting. Rows are inserted in run order directly above the
`^errorTable` anchor, so reading top-to-bottom is chronological — all a scan needs.

---

## Rules

- **One row per failure**, then continue the run. A logged error is not a reason to
  abort unless the calling skill says so.
- **Do not log clean, expected outcomes** — "no new posts", a post skipped by the
  draft/topic/date filter, a listing already applied to. Only genuine failures.
- **Findings are not errors.** What a skill *finds* — audit issues, lint hits, scan
  results, "no results for this query" — belongs in that skill's own report or output file,
  never in `Errors.md`. This log is for the run breaking (fetch failed, not logged in, browser
  won't start, usage abort), not for what the run discovered.
- **Escaping is mandatory.** Error text routinely contains `|` (URLs, shell output)
  and can contain newlines; the `log_error` helper handles both. Don't hand-write
  rows that skip it.
- **Always write through `log_error`.** It takes `.Errors.lock` before splicing the row in
  above `^errorTable` and writes via temp file + `mv`. Don't hand-edit the table or remove
  the lock — a lock-free read-modify-write drops other skills' rows.

---

## Agent writers (out of this folder)

Agent writers outside the skill library live in the agent code, not the Cowork skill
library. Point them at the same `$OBSIDIAN_VAULT/Errors.md` with the same schema and the
same locked insert-above-`^errorTable` procedure, using `source: agent` and the repo name
in `item` (e.g. `basin`) — they can't be edited from the skill folder.

---

## iCloud caveat

The vault is iCloud-synced. The `.Errors.lock` + temp-file-`mv` write protects concurrent
writers **on one machine**. If two machines write while offline, iCloud makes an
`Errors 2.md` conflict copy rather than merging. Keep error-logging skills running on the one
always-on Mac (the work Mac stays silent by default) and this never triggers.
