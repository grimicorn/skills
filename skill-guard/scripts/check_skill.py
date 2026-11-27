#!/usr/bin/env python3
"""
check_skill.py -- deterministic pre-package guard for skills.

Refuses to bless a skill folder that would silently lose files on install.
All checks are deterministic string/filesystem checks. No LLM judgement, so a
malformed or hostile SKILL.md cannot talk its way past it.

Checks per skill:
  1. SKILL.md exists.
  2. YAML frontmatter parses and carries a non-empty `name:`.
  3. Folder basename == `name:` (THE root cause: a misnamed working folder makes
     package/install misplace the references/ and scripts/ subfolders).
  4. Reference integrity: every bundled file the SKILL.md points at
     (references/<f>, scripts/<f>, assets/<f>) actually exists in the folder.

Exit code 0 = all checked skills pass. Non-zero = at least one problem.

Usage:
  python3 check_skill.py /path/to/skill-folder
  python3 check_skill.py --all /path/to/skills-root
  python3 check_skill.py --all /path/to/skills-root --json   # structured output
"""

import argparse
import json
import os
import re
import sys

# Library skills that legitimately MENTION other skills' bundled files in their
# prose (they own none of their own). Reference-integrity is skipped for these.
# To exempt a new one, add its folder name here. The folder-name check below
# always applies, even to these.
IGNORE_REFS = {
    "shared-playwright-browser",
    "shared-untrusted-content",
    "skill-librarian",
}

# Matches a bare `references/foo.md`, `scripts/foo.py`, `assets/foo.png` token.
# The lookbehind rejects tokens that are part of a longer path
# (e.g. `skill-scanner/scripts/scan.py` or `/mnt/.../scripts/x.py`), so a mention
# of another skill's file is not treated as this skill's own bundled file.
REF_TOKEN = re.compile(
    r"(?<![\w./~-])(references|scripts|assets)/([A-Za-z0-9_.\-]+\.[A-Za-z0-9]+)"
)


def frontmatter_name(text):
    """Return the `name:` value from leading --- frontmatter, quotes stripped."""
    if not text.startswith("---"):
        return None
    lines = text.split("\n")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None
    for line in lines[1:end]:
        m = re.match(r"\s*name\s*:\s*(.+?)\s*$", line)
        if m:
            val = m.group(1).strip()
            if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
                val = val[1:-1]
            return val.strip()
    return None


def check_skill(folder):
    """Return a list of problem dicts: {skill, check, detail}. Empty == clean."""
    folder = folder.rstrip("/")
    disk_name = os.path.basename(folder)
    problems = []

    skill_md = os.path.join(folder, "SKILL.md")
    if not os.path.isfile(skill_md):
        return [{"skill": disk_name, "check": "no-skill-md", "detail": "no SKILL.md in folder"}]

    with open(skill_md, encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    name = frontmatter_name(text)
    if not name:
        problems.append({"skill": disk_name, "check": "no-name",
                         "detail": "SKILL.md frontmatter has no parseable `name:`"})
    elif name != disk_name:
        problems.append({"skill": disk_name, "check": "name-mismatch",
                         "detail": f"folder='{disk_name}' name='{name}'; rename the folder to "
                                   f"'{name}' before packaging (install misplaces bundled files)"})

    if disk_name not in IGNORE_REFS:
        seen = set()
        for m in REF_TOKEN.finditer(text):
            tok = f"{m.group(1)}/{m.group(2)}"
            if tok in seen:
                continue
            seen.add(tok)
            if not os.path.isfile(os.path.join(folder, tok)):
                problems.append({"skill": disk_name, "check": "missing-reference",
                                 "detail": f"SKILL.md references `{tok}` but that file is missing "
                                           f"from the folder (would ship an incomplete package)"})
    return problems


def main():
    ap = argparse.ArgumentParser(description="Deterministic pre-package guard for skills.")
    ap.add_argument("path", help="a skill folder, or a skills root with --all")
    ap.add_argument("--all", action="store_true", help="check every skill subfolder of PATH")
    ap.add_argument("--json", action="store_true", help="emit structured JSON")
    args = ap.parse_args()

    if args.all:
        folders = sorted(
            os.path.join(args.path, d)
            for d in os.listdir(args.path)
            if os.path.isfile(os.path.join(args.path, d, "SKILL.md"))
        )
    else:
        folders = [args.path]

    problems = []
    for f in folders:
        problems.extend(check_skill(f))

    exit_code = 1 if problems else 0

    if args.json:
        print(json.dumps({"checked": len(folders), "problems": problems,
                          "exit_code": exit_code}, indent=2))
        sys.exit(exit_code)

    if not folders:
        print("No skills found to check.")
        sys.exit(2)

    if problems:
        print("GUARD FAILED -- do not package:")
        for p in problems:
            print(f"  x {p['skill']}: [{p['check']}] {p['detail']}")
        print(f"\n{len(problems)} problem(s) across {len(folders)} skill(s).")
        sys.exit(1)

    print(f"GUARD PASSED: {len(folders)} skill(s) checked, no problems.")
    sys.exit(0)


if __name__ == "__main__":
    main()
