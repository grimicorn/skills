#!/usr/bin/env python3
"""
package_skill_guarded.py -- run the deterministic guard, then package only if it passes.

Drop-in replacement for `python -m scripts.package_skill <src> <out>`. Use this
instead of calling package_skill directly, so a misnamed folder or a missing
bundled file can never ship.

  python3 package_skill_guarded.py <skill-folder> <output-dir>

Steps:
  1. Run check_skill.py on the SOURCE folder. Abort on any failure.
  2. Call Anthropic's package_skill to build the .skill.
  3. Re-extract the built .skill and re-run the guard on the EXTRACTED copy, so a
     packaging-time drop or rename is caught too.

The skill-creator location is auto-discovered across the layouts Cowork uses
(bundled examples, a mounted .claude/skills folder, ~/.claude/skills in a cloud
container). Override it with the SKILL_CREATOR_DIR environment variable.
"""

import glob
import os
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.join(HERE, "check_skill.py")

# Ordered candidates. The first one containing scripts/package_skill.py wins.
# Cloud Cowork sessions have no /mnt/skills at all, which is why this is a search
# and not a single hardcoded default.
_CANDIDATES = [
    "/mnt/skills/examples/skill-creator",
    "/mnt/skills/user/skill-creator",
    os.path.expanduser("~/.claude/skills/skill-creator"),
]


def _find_skill_creator():
    override = os.environ.get("SKILL_CREATOR_DIR")
    if override:
        return override
    # A sibling skill-creator next to this skill's own folder, whatever the root is.
    sibling = os.path.join(os.path.dirname(os.path.dirname(HERE)), "skill-creator")
    for cand in [sibling] + _CANDIDATES + sorted(
        glob.glob("/sessions/*/mnt/.claude/skills/skill-creator")
    ):
        if os.path.isfile(os.path.join(cand, "scripts", "package_skill.py")):
            return cand
    return None


SKILL_CREATOR_DIR = _find_skill_creator()


def guard(path):
    return subprocess.run([sys.executable, CHECK, path]).returncode


def main():
    if len(sys.argv) != 3:
        print("usage: package_skill_guarded.py <skill-folder> <output-dir>")
        sys.exit(2)

    src = sys.argv[1].rstrip("/")
    out = sys.argv[2]
    name = os.path.basename(src)

    print("== guard: source ==")
    if guard(src) != 0:
        print("Refusing to package: source failed the guard.")
        sys.exit(1)

    print("== packaging ==")
    if not SKILL_CREATOR_DIR:
        print(
            "Could not locate skill-creator (looked for scripts/package_skill.py in the\n"
            "sibling skill folder, /mnt/skills/examples, /mnt/skills/user, ~/.claude/skills,\n"
            "and /sessions/*/mnt/.claude/skills).\n"
            "Set SKILL_CREATOR_DIR to its folder and re-run."
        )
        sys.exit(1)
    print(f"   using skill-creator at {SKILL_CREATOR_DIR}")
    r = subprocess.run(
        [sys.executable, "-m", "scripts.package_skill", os.path.abspath(src), os.path.abspath(out)],
        cwd=SKILL_CREATOR_DIR,
    )
    if r.returncode != 0:
        print("package_skill failed.")
        sys.exit(r.returncode)

    skill_file = os.path.join(out, f"{name}.skill")
    if not os.path.isfile(skill_file):
        print(f"Expected {skill_file} but package_skill did not produce it.")
        sys.exit(1)

    print("== guard: built package ==")
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(skill_file) as z:
            z.extractall(tmp)
        extracted = os.path.join(tmp, name)
        if not os.path.isdir(extracted):
            print(f"Built package has no top-level '{name}/' folder -- name mismatch.")
            sys.exit(1)
        if guard(extracted) != 0:
            print("Built package failed the guard (packaging dropped or misnamed a file).")
            sys.exit(1)

    print(f"OK: {skill_file} passed the guard.")


if __name__ == "__main__":
    main()
