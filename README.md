# Claude skills

A working subset of a personal Claude skill library, published to show how
the pieces fit together, not as a drop-in install.

## What's here

- **Library tooling**: `skill-guard` (blocks broken packages before they ship),
  `skill-scanner` (static scan for malicious or footgun patterns),
  `skill-librarian` (audits the library for drift and duplication),
  `skill-fixer` (applies only the audit findings you approved).
- **Shared libs**: environment constants, one error log schema, usage-limit
  checks, browser session handling, and a prompt-injection protocol for
  untrusted content.
- **Orchestrator example**: `orchestrator-content-ingest` running
  `research-nightly` and `youtube-transcript` with shared setup and one report.

## Skills mentioned but not included

Some files name skills that aren't in this repo (`blog-post-creator`,
`seo-audit`, `shared-playwright-browser`, the cross-posters, and others).
They're part of the private library and tied to specific sites and accounts.
The references are left in because they show how the shared libs get used.

## Setup

1. Fill in `shared-env/scripts/env.sh`.
2. Keep secrets out of the repo; the skills only reference variable names.
3. Run `skill-guard` before packaging any skill.

## How this repo is maintained

It's generated from a private repo. An allowlist picks which skills are
exported, literals are swapped for placeholders, and the build fails on any
leftover personal term, reference to an unpublished skill, or secret.
PRs from that export are reviewed before merging.

## License

MIT. See `LICENSE`.
