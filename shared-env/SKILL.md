---
name: "shared-env"
description: "Library skill, not user-triggered. Provides shared constants and the Cowork environment guard used by other skills. Read this skill whenever another skill instructs you to run the environment check or reference Obsidian vault paths."
---

# Shared: Environment & Constants

A library of shared constants and procedures. Not triggered directly by users;
referenced from other skills by path.

> **Public template.** The values below are placeholders. Set your own in
> [`scripts/env.sh`](scripts/env.sh); nothing else in the library should need editing.

---

## Constants

Use these values wherever the paths, URLs, or repo name appear in a calling skill:

```
OBSIDIAN_VAULT      = /Users/you/Library/Mobile Documents/<obsidian-icloud-folder>/Documents/Vault/Claude

BLOG_GITHUB_REPO    = your-org/your-blog
BLOG_GITHUB_BRANCH  = main
BLOG_LOCAL_REPO     = /Users/you/Development/your-blog

BLOG_POSTS_PATH     = content/posts
BLOG_DATA_PATH      = data
BLOG_IMAGES_PATH    = public/images

BLOG_URL            = https://example.com
BLOG_POSTS_URL      = https://example.com/posts

BLOG_RAW_BASE       = https://raw.githubusercontent.com/$BLOG_GITHUB_REPO/$BLOG_GITHUB_BRANCH

ARTICLE_TOPICS      = development, ai
```

**`BLOG_RAW_BASE`** is the only sanctioned way to build a raw-content URL into the blog repo.
Build it from `$BLOG_RAW_BASE` plus a `BLOG_*_PATH`; never paste a
`raw.githubusercontent.com` URL with the repo name baked in.

**Contents-API URLs** are built inline as
`https://api.github.com/repos/$BLOG_GITHUB_REPO/contents/<path>`. There is deliberately no
`BLOG_API_BASE` constant: the repo name still comes from `$BLOG_GITHUB_REPO`, so a repo rename
is a one-line change here either way. Never bake the literal repo name or a literal content
path into a skill.

---

## Loading the constants in bash

The constants above are **not** to be retyped as literals inside a calling skill's `bash` block.
Source them from [`scripts/env.sh`](scripts/env.sh), which is the single place the values live:

```bash
SKILLS_ROOT="$(ls -d /mnt/skills/user 2>/dev/null || ls -d /sessions/*/mnt/.claude/skills 2>/dev/null | head -1)"
. "$SKILLS_ROOT/shared-env/scripts/env.sh"
```

Every constant is then exported into the shell. `OBSIDIAN_VAULT` resolves to the Mac path
when bash can see it and falls back to the Cowork sandbox mount (`/sessions/*/mnt/Claude`)
otherwise, so it is always the path **bash** should write to. `OBSIDIAN_VAULT_MAC` is always the
Mac-side path; use that one whenever a path is handed to something that runs on the Mac rather
than in the sandbox (e.g. a Chrome `file_upload`).

If `env.sh` cannot be sourced, stop and tell the user the skill library is not reachable. Do not
substitute a hardcoded path.

**`ARTICLE_TOPICS`** is the canonical list of `topic` frontmatter values for written blog posts.
When a topic is added, update it **here** and in every skill that classifies or filters by topic.

The one sanctioned exception to "no literals" is a skill's YAML `description`. Descriptions are
trigger text matched before any constant is resolved, so a bare domain there is correct and is
**not** constant drift.

**`BLOG_LOCAL_REPO`** is the on-disk checkout of `$BLOG_GITHUB_REPO` on the automation machine.
Skills that rely on it must preflight that the path exists, is a git repo, and has its tooling
installed before use.

Ensure the vault directory exists before any write:

```bash
mkdir -p "$OBSIDIAN_VAULT/"
```

---

## Environment Check

Run at the very start of any Cowork-only skill, before any other work.

The bash sandbox maps the Obsidian vault to a session-scoped mount path rather
than the Mac filesystem path. Run both checks; if either succeeds, the
environment is Cowork and you should proceed.

```bash
SKILLS_ROOT="$(ls -d /mnt/skills/user 2>/dev/null || ls -d /sessions/*/mnt/.claude/skills 2>/dev/null | head -1)"
. "$SKILLS_ROOT/shared-env/scripts/env.sh" 2>/dev/null

# Check 1: Mac filesystem path (works if bash has direct Mac access)
MAC_OK=0
test -d "$OBSIDIAN_VAULT_MAC" && MAC_OK=1

# Check 2: Sandbox mount path (works in the isolated Linux bash sandbox).
# Check the vault folder itself, not a marker file inside it: a marker file
# breaks the check for every skill the day it's moved.
SANDBOX_OK=0
ls -d /sessions/*/mnt/Claude 2>/dev/null | grep -q . && SANDBOX_OK=1

if [ "$MAC_OK" = "1" ] || [ "$SANDBOX_OK" = "1" ]; then
  echo "cowork"
else
  echo "other"
fi
```

- **`cowork`** → proceed normally.
- **`other`** → stop immediately and respond:

  > "This skill requires Cowork to access your Obsidian vault and browser. Please run it there."

  Do not continue past this point.

---

## Date Format

All dates written to Obsidian log files use this format:

```
May 8th, 2026
```

Rules:
- Month name spelled out, not abbreviated
- Day uses ordinal suffix: 1st, 2nd, 3rd, then 4th to 20th, then 21st, 22nd, 23rd, 24th to 30th, 31st
- The 11th, 12th, 13th always use -th (not -st/-nd/-rd)
- Full 4-digit year
