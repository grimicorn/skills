#!/usr/bin/env python3
"""
parse_audit.py -- deterministic reader/writer for the Skill Audit report.

The audit report is a markdown file with one dated section per run. This script
owns every read and write of its findings tables so the apply loop never has to
eyeball markdown. No LLM judgement is involved: which rows are approved is a
plain string check on a status cell, not an interpretation of the fix text.

Modes:
  --list          Print the latest run's rows as JSON.
  --add-status    Backfill a `status` column (blank) into the latest run's tables.
  --mark          Set the status cell of one row: --mark done --row-id <id>
  --sections      Print the dated section headings found, newest first.
  --overview      Recompute the `## Overview` totals table (^overviewTable) from the
                  latest run and rewrite only that table. Creates it if missing.

Row ids are stable within a run: "<severity>:<line-number>" of the row's line in
the file, e.g. "medium:31". A row id is only valid until the file is rewritten.

Usage:
  python3 parse_audit.py "<report path>" --list
  python3 parse_audit.py "<report path>" --add-status
  python3 parse_audit.py "<report path>" --mark done --row-id medium:31 --note "Aug 22nd, 2026"
  python3 parse_audit.py "<report path>" --overview
"""

import argparse
import json
import os
import re
import shutil
import sys

SEVERITIES = ("high", "medium", "low")
VALID_STATUS = ("apply", "skip", "defer", "done", "packaged", "failed", "")
STATUS_HEADER = "status"

# Rows in these states count as clean until the next librarian run. `packaged` = built and
# passed the guard (not yet installed); `done` = live or baselined; `skip` = the user ruled it not
# a finding. Everything else (blank, apply, defer, failed) still counts against its severity.
RESOLVED_STATUS = ("packaged", "done", "skip")
OVERVIEW_ANCHOR = "^overviewTable"
CLEAN_RE = re.compile(r"^###\s+Clean\s*$", re.IGNORECASE)

SECTION_RE = re.compile(r"^##\s+(.+?)\s+[-—]{1,2}\s*Audit\s*$")
SEV_RE = re.compile(r"^###\s+(High|Medium|Low)\s*$", re.IGNORECASE)


def split_row(line):
    """Split a markdown table row into cells, honouring \\| escapes."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells, cur, i = [], "", 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body) and body[i + 1] == "|":
            cur += "\\|"
            i += 2
            continue
        if ch == "|":
            cells.append(cur.strip())
            cur = ""
            i += 1
            continue
        cur += ch
        i += 1
    cells.append(cur.strip())
    return cells


def is_separator(cells):
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c != "")


def latest_section(lines):
    """Return (start, end) line indices of the newest `## ... - Audit` section.

    Newest means the FIRST such heading in the file: the librarian prepends each
    run above the previous one. If no dated heading exists the whole file is used.
    """
    starts = [i for i, l in enumerate(lines) if SECTION_RE.match(l.rstrip())]
    if not starts:
        return 0, len(lines)
    start = starts[0]
    end = starts[1] if len(starts) > 1 else len(lines)
    return start, end


def parse(lines, start, end):
    """Yield dicts describing every findings row in [start, end)."""
    sev = None
    header = None
    rows = []
    for i in range(start, end):
        raw = lines[i].rstrip("\n")
        m = SEV_RE.match(raw.strip())
        if m:
            sev = m.group(1).lower()
            header = None
            continue
        if sev is None or not raw.lstrip().startswith("|"):
            continue
        cells = split_row(raw)
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if is_separator(cells):
            continue
        rec = {"id": "%s:%d" % (sev, i + 1), "severity": sev, "line": i + 1}
        for name, val in zip(header, cells):
            rec[name or "col"] = val
        rec.setdefault(STATUS_HEADER, None)
        rows.append(rec)
    return rows


def placeholder(rec):
    """A librarian 'no findings this run' filler row, not a real finding."""
    skill = (rec.get("skill") or "").strip()
    return skill in ("", "-", "—")


def cmd_list(path, lines):
    start, end = latest_section(lines)
    heading = lines[start].strip() if SECTION_RE.match(lines[start].rstrip()) else None
    rows = parse(lines, start, end)
    real = [r for r in rows if not placeholder(r)]
    has_status = all(r.get(STATUS_HEADER) is not None for r in real) if real else False
    out = {
        "report": path,
        "section": heading,
        "has_status_column": has_status,
        "counts": {s: len([r for r in real if r["severity"] == s]) for s in SEVERITIES},
        "rows": real,
    }
    approved = [r for r in real if (r.get(STATUS_HEADER) or "").lower() == "apply"]
    out["approved"] = [r["id"] for r in approved]
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if has_status or not real else 3


def backup(path):
    bak = path + ".bak-skill-fixer"
    shutil.copy2(path, bak)
    return bak


def cmd_add_status(path, lines):
    start, end = latest_section(lines)
    sev = None
    header_seen = False
    changed = 0
    out = list(lines)
    for i in range(start, end):
        raw = out[i].rstrip("\n")
        if SEV_RE.match(raw.strip()):
            sev = SEV_RE.match(raw.strip()).group(1).lower()
            header_seen = False
            continue
        if sev is None or not raw.lstrip().startswith("|"):
            continue
        cells = split_row(raw)
        if not header_seen:
            header_seen = True
            if cells and cells[0].lower() == STATUS_HEADER:
                sev = sev  # already has the column; leave this table alone
                header_seen = "done"
                continue
            out[i] = "| " + " | ".join([STATUS_HEADER] + cells) + " |\n"
            changed += 1
            continue
        if header_seen == "done":
            continue
        if is_separator(cells):
            out[i] = "| " + " | ".join(["-----"] + cells) + " |\n"
            continue
        out[i] = "| " + " | ".join([""] + cells) + " |\n"
        changed += 1
    if changed:
        bak = backup(path)
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(out)
        print("added status column to %d line(s); backup at %s" % (changed, bak))
    else:
        print("status column already present; nothing changed")
    return 0


def cmd_mark(path, lines, row_id, status, note):
    if status not in VALID_STATUS:
        print("invalid status %r (allowed: %s)" % (status, ", ".join(VALID_STATUS)), file=sys.stderr)
        return 2
    try:
        _sev, lineno = row_id.split(":")
        idx = int(lineno) - 1
    except ValueError:
        print("bad --row-id %r (expected <severity>:<line>)" % row_id, file=sys.stderr)
        return 2
    if idx < 0 or idx >= len(lines) or not lines[idx].lstrip().startswith("|"):
        print("row-id %s does not point at a table row" % row_id, file=sys.stderr)
        return 2
    cells = split_row(lines[idx].rstrip("\n"))
    if not cells:
        print("row-id %s has no cells" % row_id, file=sys.stderr)
        return 2
    value = status if not note else "%s (%s)" % (status, note)
    cells[0] = value
    out = list(lines)
    out[idx] = "| " + " | ".join(cells) + " |\n"
    bak = backup(path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(out)
    print("marked %s -> %s; backup at %s" % (row_id, value, bak))
    return 0


def status_word(rec):
    """`packaged (2026-10-21)` -> `packaged`."""
    return (rec.get(STATUS_HEADER) or "").strip().split(" ", 1)[0].split("(", 1)[0].lower()


def split_skills(cell):
    return [n.strip().strip("`").strip() for n in (cell or "").split(",") if n.strip().strip("`").strip()]


def clean_list(lines, start, end):
    """Skill names under the latest run's `### Clean` heading."""
    names, inside = [], False
    for i in range(start, end):
        raw = lines[i].strip()
        if CLEAN_RE.match(raw):
            inside = True
            continue
        if inside:
            if raw.startswith("#"):
                break
            if raw and raw.lower().strip("_*() ") not in ("none", "-", "—"):
                names += split_skills(raw)
    return names


def overview_counts(lines):
    """High/Medium/Low = open finding rows; Clean = skills with no open rows.

    A skill is clean if the librarian listed it under `### Clean`, or every row naming it
    (including multi-skill rows) is packaged/done/skip.
    """
    start, end = latest_section(lines)
    real = [r for r in parse(lines, start, end) if not placeholder(r)]
    counts = {s: 0 for s in SEVERITIES}
    open_skills, resolved_skills = set(), set()
    for r in real:
        names = split_skills(r.get("skill"))
        if status_word(r) in RESOLVED_STATUS:
            resolved_skills.update(names)
        else:
            counts[r["severity"]] += 1
            open_skills.update(names)
    clean = set(clean_list(lines, start, end)) | resolved_skills
    counts["clean"] = len(clean - open_skills)
    return counts


def overview_table(c):
    return [
        "| High | Medium | Low | Clean |\n",
        "| ---- | ------ | --- | ----- |\n",
        "| %d | %d | %d | %d |\n" % (c["high"], c["medium"], c["low"], c["clean"]),
    ]


def cmd_overview(path, lines):
    c = overview_counts(lines)
    out = list(lines)
    anchor = next((i for i, l in enumerate(out) if l.strip() == OVERVIEW_ANCHOR), None)
    if anchor is not None:
        # Replace only the contiguous table directly above the anchor.
        top = anchor
        while top > 0 and out[top - 1].lstrip().startswith("|"):
            top -= 1
        table = overview_table(c)
        out[top:anchor] = table
        anchor = top + len(table)
        # Anchor Rule: the line under ^overviewTable must be blank or EOF.
        if anchor + 1 < len(out) and out[anchor + 1].strip():
            out.insert(anchor + 1, "\n")
    else:
        # No overview yet: insert after frontmatter, before the first dated section.
        at = 0
        if out and out[0].strip() == "---":
            at = next((i + 1 for i in range(1, len(out)) if out[i].strip() == "---"), 0)
        while at < len(out) and not out[at].strip():
            at += 1
        out[at:at] = ["## Overview\n", "\n"] + overview_table(c) + [OVERVIEW_ANCHOR + "\n", "\n"]
    changed = out != lines
    if changed:
        c["backup"] = backup(path)
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(out)
    c["changed"] = changed
    json.dump(c, sys.stdout)
    sys.stdout.write("\n")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--add-status", action="store_true")
    ap.add_argument("--sections", action="store_true")
    ap.add_argument("--overview", action="store_true")
    ap.add_argument("--mark")
    ap.add_argument("--row-id")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    if not os.path.isfile(args.report):
        print("report not found: %s" % args.report, file=sys.stderr)
        return 2
    with open(args.report, encoding="utf-8") as fh:
        lines = fh.readlines()

    if args.sections:
        for i, l in enumerate(lines):
            if SECTION_RE.match(l.rstrip()):
                print("%d: %s" % (i + 1, l.strip()))
        return 0
    if args.overview:
        return cmd_overview(args.report, lines)
    if args.add_status:
        return cmd_add_status(args.report, lines)
    if args.mark:
        if not args.row_id:
            print("--mark requires --row-id", file=sys.stderr)
            return 2
        return cmd_mark(args.report, lines, args.row_id, args.mark, args.note)
    return cmd_list(args.report, lines)


if __name__ == "__main__":
    sys.exit(main())
