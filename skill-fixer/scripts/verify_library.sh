#!/usr/bin/env bash
# verify_library.sh -- re-run every deterministic layer over the skill library.
#
#   bash verify_library.sh <library-root> [--suppressions FILE] [--snapshot OUT.json]
#                                         [--before OUT.json]
#
# Two calls per fix run:
#   BEFORE any edit:  verify_library.sh "$ROOT" --suppressions "$S" --snapshot /tmp/before.json
#   AFTER  the edits: verify_library.sh "$ROOT" --suppressions "$S" --before   /tmp/before.json
#
# Layers:
#   1. skill-guard   (check_skill.py --all)  -- packaging integrity, must be clean outright
#   2. skill-scanner (scan.py --json)        -- fails only on findings NEW since the snapshot
#   3. block-anchor placement                -- skill-librarian check H, must be clean outright
#
# Why the snapshot: the library legitimately carries unsuppressed findings the fixer never
# touched (a freshly installed Anthropic skill, an un-baselined line). Failing on those would
# make every run red and train you to ignore the verifier. What matters is whether THIS run
# introduced something.
#
# Exit 0 = nothing regressed. Non-zero = a fix broke something; do not report the run as done.

set -u

ROOT=""
SUPPRESSIONS=""
SNAPSHOT=""
BEFORE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --suppressions) SUPPRESSIONS="${2:-}"; shift 2 ;;
    --snapshot)     SNAPSHOT="${2:-}";     shift 2 ;;
    --before)       BEFORE="${2:-}";       shift 2 ;;
    -*) echo "unknown flag: $1" >&2; exit 2 ;;
    *)  ROOT="$1"; shift ;;
  esac
done
[ -n "$ROOT" ] || { echo "usage: verify_library.sh <library-root> [--suppressions F] [--snapshot F|--before F]" >&2; exit 2; }

FAIL=0
SCAN_JSON="${SNAPSHOT:-/tmp/skill-fixer-scan-after.json}"

find_script() {
  for c in "$ROOT/$1/scripts/$2" "$HOME/.claude/skills/$1/scripts/$2"; do
    [ -f "$c" ] && { printf '%s' "$c"; return 0; }
  done
  return 1
}

echo "== 1. skill-guard =="
if GUARD="$(find_script skill-guard check_skill.py)"; then
  python3 "$GUARD" --all "$ROOT" || FAIL=1
else
  echo "SKIP: skill-guard not found under $ROOT — integrity NOT verified"
  FAIL=1
fi

echo
echo "== 2. skill-scanner =="
if SCAN="$(find_script skill-scanner scan.py)"; then
  if [ -n "$SUPPRESSIONS" ] && [ -f "$SUPPRESSIONS" ]; then
    python3 "$SCAN" "$ROOT" --json --suppressions "$SUPPRESSIONS" > "$SCAN_JSON"
  else
    echo "note: no suppressions file — baselined findings will show as live"
    python3 "$SCAN" "$ROOT" --json > "$SCAN_JSON"
  fi
  echo "scan JSON: $SCAN_JSON"
  if [ -n "$SNAPSHOT" ]; then
    python3 - "$SCAN_JSON" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
live = [f for f in d.get("findings", []) if not f.get("suppressed")]
print("snapshot recorded: %d finding(s), %d live after suppressions" % (len(d.get("findings", [])), len(live)))
for f in live:
    if f.get("severity") in ("critical", "high"):
        print("  pre-existing %s %s:%s %s" % (f["severity"], f["file"], f["line"], f["note"]))
PY
  else
    python3 - "$SCAN_JSON" "${BEFORE:-}" <<'PY'
import json, sys
after = json.load(open(sys.argv[1]))
live = [f for f in after.get("findings", []) if not f.get("suppressed")]
before_path = sys.argv[2] if len(sys.argv) > 2 else ""
known = set()
if before_path:
    try:
        b = json.load(open(before_path))
        known = {f.get("fingerprint") for f in b.get("findings", [])}
    except Exception as e:
        print("WARN: could not read snapshot %s (%s) — treating every live finding as new" % (before_path, e))
else:
    print("WARN: no --before snapshot — treating every live finding as new")
new = [f for f in live if f.get("fingerprint") not in known]
carried = len(live) - len(new)
print("live findings: %d (%d carried over from before the fixes, %d NEW)" % (len(live), carried, len(new)))
bad = [f for f in new if f.get("severity") in ("critical", "high", "medium")]
for f in new:
    print("  NEW %s %s:%s %s" % (f["severity"], f["file"], f["line"], f["note"]))
sys.exit(1 if bad else 0)
PY
    [ $? -eq 0 ] || FAIL=1
  fi
else
  echo "SKIP: skill-scanner not found under $ROOT — malware scan NOT verified"
  FAIL=1
fi

echo
echo "== 3. block-anchor placement =="
# Flags any ^anchor line NOT followed by a blank line or EOF. Fenced-block ends are ignored.
ANCHOR_OUT="$(
  find "$ROOT" -name "*.md" -not -path "*/.obsidian/*" -print0 2>/dev/null | while IFS= read -r -d '' f; do
    awk -v F="$f" '
      { lines[NR] = $0 }
      /^\^[A-Za-z0-9-]+[[:space:]]*$/ { ids[NR] = $0 }
      END {
        for (n in ids) {
          nxt = (n+1 in lines) ? lines[n+1] : "<EOF>"
          if (nxt != "<EOF>" && nxt !~ /^[[:space:]]*$/ && nxt !~ /^```/)
            printf "FAIL  %s:%d  %s  -> next line: \"%s\"\n", F, n, ids[n], nxt
        }
      }' "$f"
  done
)"
if [ -n "$ANCHOR_OUT" ]; then
  printf '%s\n' "$ANCHOR_OUT"
  FAIL=1
else
  echo "OK: every block anchor is followed by a blank line or EOF"
fi

echo
if [ -n "$SNAPSHOT" ]; then
  [ "$FAIL" = "0" ] && echo "SNAPSHOT: taken, library clean going in" \
                    || echo "SNAPSHOT: taken, but the library ALREADY fails a layer — fix that first"
else
  [ "$FAIL" = "0" ] && echo "VERIFY: clean — nothing regressed" \
                    || echo "VERIFY: FAILED — do not report the fix run as done"
fi
exit "$FAIL"
