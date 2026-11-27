# Claude Skills

A working slice of a personal [Claude skill](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) library: 12 of the 48 skills that run my scheduled automation, published to show how a larger library holds together.

This isn't a plugin pack you install and forget. Most of these skills assume an Obsidian vault, a Claude session that can run shell commands, and the conventions described below. They're most useful as reference: how the pieces divide up, what's shared, and what keeps a library of dozens of skills from drifting apart.

## What's here

### Library tooling

Skills that keep the other skills honest. The checks are deterministic scripts, not model judgement, so a malformed or hostile `SKILL.md` can't talk its way past them.

| Skill | What it does |
| --- | --- |
| [`skill-guard`](skill-guard) | Pre-package check. Refuses a skill whose folder name doesn't match its `name:` frontmatter, or that references a bundled `references/`, `scripts/`, or `assets/` file that isn't there. Those two mistakes silently drop files on install. |
| [`skill-scanner`](skill-scanner) | Static scan for malicious or footgun patterns: hidden or bidi unicode, obfuscated `eval`/`exec`, credential-file reads next to network egress, writes to agent config, `curl \| sh`, and instruction-smuggling phrasing. Known-good findings are suppressed by fingerprint, so an edit to that line re-fires them. |
| [`skill-librarian`](skill-librarian) | Audits the whole library for convention drift, duplicated logic, broken cross-references, hardcoded constants, and missing prompt-injection hardening. Writes a ranked report and changes nothing. |
| [`skill-fixer`](skill-fixer) | Applies only the audit findings a person has marked `apply`, in a throwaway copy of the library, then re-runs the guard and scanner before handing back the fixed skills. |

### Shared libraries

Not triggered directly. Other skills link to them by path, so each convention lives in one place.

| Skill | What it does |
| --- | --- |
| [`shared-env`](shared-env) | The only place paths, repo names, and URLs live, plus an environment check for skills that need the vault. Fill in [`scripts/env.sh`](shared-env/scripts/env.sh) to use any of the others. |
| [`shared-error-log`](shared-error-log) | One error log for every skill: a single Markdown table (`date \| source \| item \| note`) with a locked insert, so concurrent scheduled runs don't drop each other's rows. |
| [`shared-usage-limits`](shared-usage-limits) | Usage thresholds for scheduled skills: skip a run before it starts, or stop cleanly mid-run, without leaving a half-written log. |
| [`shared-untrusted-content`](shared-untrusted-content) | The prompt-injection protocol for anything fetched: web pages, transcripts, feeds, API responses. Fetched text is data to reason about, never instructions, and skills declare an allowlist of the actions they may take. |
| [`shared-browser`](shared-browser) | Browser session setup, tab tracking, and cleanup, so a skill never closes a tab it didn't open. |

### A worked example

| Skill | What it does |
| --- | --- |
| [`orchestrator-content-ingest`](orchestrator-content-ingest) | Runs the two skills below in one pass with shared setup and one combined report. |
| [`research-nightly`](research-nightly) | Works through a queue of questions in a vault note, writes a sourced answer note for each, and clears the queue. |
| [`youtube-transcript`](youtube-transcript) | Transcribes a YouTube playlist into vault notes with a summary, then removes each video from the playlist. |

## Conventions worth stealing

- **Library skills over copy-paste.** Anything two skills both need (constants, error logging, browser setup, usage checks) moves into a `shared-*` skill and gets linked by path.
- **No literals outside `shared-env`.** A repo rename is a one-line change. The one exception is a skill's `description`, which is trigger text matched before any constant resolves.
- **Every side-effecting skill declares an action allowlist.** It says exactly what the skill may write, post, or push, and what it must never do, so injected text has nothing to escalate to.
- **Deterministic gates before packaging.** `skill-guard` and `skill-scanner` run on every change. Neither one asks a model whether something looks fine.
- **One error log.** Every skill writes failures to the same table in the same format, which makes "what broke this week" a single file to read.

## Using these

1. Copy the skills you want, including every `shared-*` skill they link to.
2. Fill in `shared-env/scripts/env.sh` with your own vault path, repo, and URLs.
3. Keep secrets out of the skills. They reference secret names only, like `GITHUB_TOKEN`; load the values from your own secret manager at run time.
4. Run `skill-guard` before packaging anything:

   ```bash
   python3 skill-guard/scripts/check_skill.py path/to/skill
   python3 skill-scanner/scripts/scan.py path/to/skill
   ```

The guard and scanner use only the Python standard library.

## Skills mentioned but not included

Some files name skills that aren't in this repo, such as `blog-post-creator`, `seo-audit`, `shared-playwright-browser`, and the cross-posters. They're part of the private library and tied to specific sites and accounts. The references are left in because they show how the shared libraries get used.

## How this repo is maintained

It's generated, not edited by hand. The full library lives in a private repo, and on every change a GitHub Action builds this one from it:

- An allowlist picks which skills are published. Everything else stays private by default, including new skills.
- Personal values (names, paths, domains, emails) are swapped for placeholders.
- The build fails on any leftover personal term, any reference to an unpublished skill that isn't cleared for mention, any binary or symlink it doesn't expect, or anything that looks like a secret. `gitleaks` runs on top of that.
- The result arrives here as a pull request that gets reviewed before it's merged.

Issues are welcome. Pull requests can't be merged directly, because the next export would overwrite them, but a good one will get ported back to the source.

## License

[MIT](LICENSE)
