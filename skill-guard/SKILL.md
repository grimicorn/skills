---
name: skill-guard
description: >
  Deterministic pre-package guard for skills. ALWAYS run this before packaging,
  building, repackaging, or updating ANY .skill file. It refuses skills whose
  folder name does not match the `name:` frontmatter, or that reference a bundled
  `references/`, `scripts/`, or `assets/` file missing from the folder -- the two
  failures that silently drop files on install. Use whenever you are about to run
  package_skill or skill-creator's packaging step, or when asked to "check a
  skill", "validate a skill before packaging", "guard the packaging", "make sure a
  skill is complete", or "lint a skill folder". Can also run library-wide with
  --all as a periodic audit. Pure Python, no LLM judgement, so a malformed or
  hostile SKILL.md cannot talk past it.
---

# Skill Guard

A deterministic gate that stops the two failure modes that silently drop a
skill's bundled files when it is installed:

1. **Folder name != `name:` frontmatter.** A misnamed working folder (e.g. a
   `concert clean` folder whose skill is `name: concert-search`) makes the packager
   and installer misplace the `references/` and `scripts/` subfolders. This is the
   root cause behind references vanishing on install. It bites hardest after a
   rename: the `name:` gets updated and the folder does not.
2. **A referenced bundled file is missing.** The SKILL.md points at a file under
   `references/`, `scripts/`, or `assets/` that is not actually in the folder, so
   the package ships incomplete.

Both checks are plain filesystem/string checks in `scripts/check_skill.py`. No
model judgement is involved, by design.

## When to run it

Run the guard **before every packaging step**. Do not call
`python -m scripts.package_skill` directly. Instead either:

- **Preferred (gated packaging):** run the wrapper, which guards the source,
  packages, then re-verifies the built archive:

  ```bash
  python3 scripts/package_skill_guarded.py /tmp/<skill-folder> /mnt/user-data/outputs
  ```

- **Or guard, then package manually:**

  ```bash
  python3 scripts/check_skill.py /tmp/<skill-folder>   # must exit 0
  cd /mnt/skills/examples/skill-creator
  python3 -m scripts.package_skill /tmp/<skill-folder> /mnt/user-data/outputs
  ```

If the guard exits non-zero, **STOP**. Do not package. Report the exact failures
and fix them (rename the folder, or restore the missing file) first.

## Library-wide audit

```bash
python3 scripts/check_skill.py --all /mnt/skills/user
```

Exits non-zero if any installed skill has a name mismatch or a missing bundled
file. Add `--json` for structured output (`{checked, problems[], exit_code}`),
which is how `skill-librarian` folds these findings into its report. Safe to wire
into a periodic `skill-librarian` run.

## Exempting library skills

A few shared/library skills mention other skills' bundled files in their prose
without owning any themselves. They are exempt from the reference-integrity check
via the `IGNORE_REFS` set at the top of `check_skill.py`. To exempt a new one, add
its folder name there. The folder-name check always applies, even to exempt
skills.

## Adjusting paths

`package_skill_guarded.py` looks for skill-creator at
`/mnt/skills/examples/skill-creator`. Override with the `SKILL_CREATOR_DIR`
environment variable if yours differs.
