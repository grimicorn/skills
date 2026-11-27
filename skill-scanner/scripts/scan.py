#!/usr/bin/env python3
"""
skill-scanner — deterministic static scanner for malicious / footgun patterns in skills.

Design contract (read this before changing anything):
  * This is a SCRIPT, not an LLM judgement. It never asks a model to evaluate
    the target. That is the whole point: the thing being scanned may be hostile
    to a model, so the model must not read it to decide. The model only runs
    this script and relays the findings.
  * All matched snippets are sanitised before they leave this script: control
    chars, zero-width chars and bidi chars are rendered as <U+XXXX> tokens and
    every snippet is truncated. A finding can therefore never smuggle an
    instruction into whatever relays the report.
  * Stdlib only. No pip installs. Runs identically in Cowork, Claude Code, and a
    bare shell. Pure filesystem reads, no network.

Usage:
  python scan.py <path>                 # scan one skill dir, or a library root
  python scan.py <path> --json          # machine-readable findings
  python scan.py <path> --show-info     # include the info/context tier
  python scan.py <path> --show-suppressed
  python scan.py <path> --suppressions FILE
  python scan.py <path> --baseline      # record every current finding as suppressed

Exit codes (after suppressions):
  0  nothing above the info tier
  1  medium / low findings only
  2  one or more critical / high findings
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

# ----------------------------------------------------------------------------
# What we read
# ----------------------------------------------------------------------------

TEXT_EXTS = {
    ".md", ".markdown", ".txt", ".py", ".pyw", ".sh", ".bash", ".zsh",
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".toml", ".rb", ".pl", ".ps1", ".env", ".cfg", ".ini",
}
SKIP_DIRS = {"__pycache__", "node_modules", ".git", ".venv", "venv", "dist", "build"}
MAX_BYTES = 1_000_000  # skip anything larger; payloads worth catching are small

SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}

# ----------------------------------------------------------------------------
# Pattern library
# ----------------------------------------------------------------------------

NETWORK_RE = re.compile(
    r"\b(requests\.(get|post|put|patch|delete)|httpx\.\w+|urllib\.request|"
    r"urlopen|http\.client|socket\.socket|aiohttp|axios|XMLHttpRequest)\b"
    r"|\bfetch\s*\(|(?<!\w)(curl|wget)\s+http|\bnc\s+-",
    re.IGNORECASE,
)

# Reads of *credential files* — distinct from reading an env var token, which
# is normal for legitimate skills. This is the high-signal half of exfil shape.
CRED_FILE_RE = re.compile(
    r"(~/?\.ssh\b|/\.ssh/|id_rsa|id_ed25519|\.aws/credentials|\.aws/config|"
    r"\.config/gcloud|\.netrc|/etc/passwd|/etc/shadow|find-generic-password|"
    r"login\.keychain|\.docker/config\.json|\.kube/config|\.npmrc|\.pypirc|"
    r"\.git-credentials)",
    re.IGNORECASE,
)

SECRET_ENV_RE = re.compile(
    r"(os\.environ(\.get)?\(?\[?['\"][A-Z0-9_]*(TOKEN|SECRET|KEY|PASSWORD|PASSWD|API)[A-Z0-9_]*['\"]"
    r"|getenv\(['\"][A-Z0-9_]*(TOKEN|SECRET|KEY|PASSWORD|API)"
    r"|process\.env\.[A-Z0-9_]*(TOKEN|SECRET|KEY|PASSWORD|API))",
)

DECODE_RE = re.compile(
    r"(base64\.(b64decode|b32decode|standard_b64decode|urlsafe_b64decode)|"
    r"bytes\.fromhex|binascii\.unhexlify|\batob\s*\(|codecs\.decode\([^)]*hex)",
)
EVAL_RE = re.compile(r"\b(eval|exec)\s*\(|new\s+Function\s*\(|(?<!\w)Function\s*\(\s*['\"]")

WRITE_INDICATOR_RE = re.compile(
    r"(>>?\s|open\([^)]*['\"][wa]\+?b?['\"]|\.write_text|\.writeText|\.write\(|"
    r"\btee\b|(?<!\w)(cp|mv|echo)\s)",
)
SELF_MODIFY_RE = re.compile(
    r"(~/?\.claude|/\.claude/|crontab|launchctl|LaunchAgents|LaunchDaemons|"
    r"~/?\.bashrc|~/?\.zshrc|\.bash_profile|/\.profile|authorized_keys|"
    r"/etc/cron|/etc/sudoers)",
    re.IGNORECASE,
)
SKILL_PATH_RE = re.compile(r"(/mnt/skills/|/\.claude/skills/|(?<!\w)skills/[a-z0-9][a-z0-9-]*/)")

DYNAMIC_SHELL_RE = re.compile(r"shell\s*=\s*True")
DYNAMIC_HINT_RE = re.compile(r"(f['\"]|\.format\(|\+\s*\w|%\s*\(|`\$\{|\$\()")
OS_SYSTEM_RE = re.compile(r"os\.system\s*\(")
CURL_PIPE_SH_RE = re.compile(r"(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba)?sh\b")

INJECTION_PHRASE_RE = re.compile(
    r"(ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+(instructions|prompts|messages|rules)"
    r"|disregard\s+(the\s+|all\s+|your\s+|previous\s+|prior\s+)"
    r"|do\s+not\s+(tell|inform|mention\s+to|notify|reveal\s+to)\s+the\s+user"
    r"|without\s+(telling|informing|notifying)\s+the\s+user"
    r"|exfiltrat|send\s+.{0,40}\s+to\s+(https?://|the\s+attacker))",
    re.IGNORECASE,
)


# ----------------------------------------------------------------------------
# Snippet sanitisation — nothing attacker-controlled leaves un-neutralised
# ----------------------------------------------------------------------------

def sanitize(text: str, limit: int = 120) -> str:
    out = []
    for ch in text:
        cp = ord(ch)
        cat = unicodedata.category(ch)
        if ch in "\t":
            out.append(" ")
        elif cp < 0x20 or cp == 0x7F or cat in ("Cf", "Co", "Cn", "Cs") or cp == 0xFEFF:
            out.append(f"<U+{cp:04X}>")
        else:
            out.append(ch)
    s = "".join(out).strip()
    if len(s) > limit:
        s = s[:limit] + "…"
    return s


def codepoint_names(chars) -> str:
    parts = []
    for ch in sorted(set(chars), key=ord):
        try:
            name = unicodedata.name(ch)
        except ValueError:
            name = "UNNAMED"
        parts.append(f"U+{ord(ch):04X} {name}")
    return "; ".join(parts)


# ----------------------------------------------------------------------------
# Finding model
# ----------------------------------------------------------------------------

class Finding:
    __slots__ = ("rule", "severity", "file", "line", "snippet", "note")

    def __init__(self, rule, severity, file, line, snippet, note):
        self.rule = rule
        self.severity = severity
        self.file = file
        self.line = line
        self.snippet = snippet
        self.note = note

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        h.update(f"{self.rule}\x00{self.file}\x00{self.snippet}".encode("utf-8", "replace"))
        return h.hexdigest()[:16]

    def to_dict(self, suppressed=False):
        return {
            "rule": self.rule,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "snippet": self.snippet,
            "note": self.note,
            "fingerprint": self.fingerprint(),
            "suppressed": suppressed,
        }


# ----------------------------------------------------------------------------
# Per-file scanning
# ----------------------------------------------------------------------------

def iter_text_files(skill_dir: Path):
    for p in sorted(skill_dir.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(skill_dir).parts):
            continue
        if p.suffix.lower() not in TEXT_EXTS:
            # allow extensionless files that start with a shebang
            if p.suffix == "":
                try:
                    head = p.open("rb").read(2)
                except OSError:
                    continue
                if head != b"#!":
                    continue
            else:
                continue
        try:
            if p.stat().st_size > MAX_BYTES:
                continue
            raw = p.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw:  # binary
            continue
        yield p, raw.decode("utf-8", "replace")


def code_line_flags(rel: str, lines):
    """Return a list of bools: is this line executable-ish code?

    Non-markdown files are code throughout. In markdown/text, only fenced code
    blocks (``` or ~~~) count as code; prose is prose. This stops markdown links
    and blockquotes (e.g. `> Read [shared-env](.../skills/...)`) from reading as
    shell redirects / writes, which is the dominant false positive.
    """
    is_md = rel.lower().endswith((".md", ".markdown", ".txt"))
    if not is_md:
        return [True] * len(lines)
    flags = []
    in_fence = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            flags.append(False)  # the fence marker line itself is not code
        else:
            flags.append(in_fence)
    return flags


def scan_file(rel: str, text: str):
    findings = []
    lines = text.splitlines()
    code = code_line_flags(rel, lines)
    code_text = "\n".join(l for l, c in zip(lines, code) if c)

    has_decode = bool(DECODE_RE.search(code_text))
    has_eval = bool(EVAL_RE.search(code_text))
    has_network = bool(NETWORK_RE.search(code_text))
    cred_lines = [(i + 1, l) for i, l in enumerate(lines) if code[i] and CRED_FILE_RE.search(l)]

    # ---- critical: hidden / invisible unicode ----------------------------
    for i, line in enumerate(lines, 1):
        bad = [ch for ch in line
               if unicodedata.category(ch) in ("Cf", "Co") or ord(ch) == 0xFEFF]
        # FEFF as a leading BOM on line 1 is benign
        if i == 1 and bad and bad[0] == "\ufeff" and line.startswith("\ufeff"):
            bad = [c for c in bad if c != "\ufeff"]
        if bad:
            findings.append(Finding(
                "hidden_unicode", "critical", rel, i, sanitize(line),
                f"invisible/bidi codepoint(s): {codepoint_names(bad)}"))

    # ---- critical: decode + eval/exec (obfuscated execution) -------------
    if has_decode and has_eval:
        ln = next((i + 1 for i, l in enumerate(lines) if code[i] and EVAL_RE.search(l)), 1)
        findings.append(Finding(
            "obfuscated_exec", "critical", rel, ln,
            sanitize(lines[ln - 1] if ln <= len(lines) else ""),
            "file both decodes a blob (base64/hex) and calls eval/exec — classic payload shape"))

    # ---- critical: credential-file read + network egress (exfil shape) ---
    if cred_lines and has_network:
        ln, line = cred_lines[0]
        findings.append(Finding(
            "exfil_credfile_egress", "critical", rel, ln, sanitize(line),
            "reads a credential file AND has network egress in the same file"))

    # ---- line-level rules ------------------------------------------------
    for i, line in enumerate(lines, 1):
        is_code = code[i - 1]

        # high: injection phrasing in any file (loudest in a SKILL.md prose)
        if INJECTION_PHRASE_RE.search(line):
            sev = "high" if rel.endswith("SKILL.md") and not is_code else "medium"
            findings.append(Finding(
                "injection_phrasing", sev, rel, i, sanitize(line),
                "instruction-smuggling phrasing — legitimate in security/doc skills, baseline if so"))

        if not is_code:
            continue  # remaining rules below are about executable code only

        # high: writing to agent config / persistence locations
        if SELF_MODIFY_RE.search(line) and WRITE_INDICATOR_RE.search(line):
            findings.append(Finding(
                "agent_self_modify", "high", rel, i, sanitize(line),
                "writes to agent config / shell rc / crontab / launchd — persistence vector"))

        # high: writing into a skills directory (a skill editing other skills)
        if SKILL_PATH_RE.search(line) and WRITE_INDICATOR_RE.search(line):
            findings.append(Finding(
                "cross_skill_write", "high", rel, i, sanitize(line),
                "write targeting a skills/ path — a skill should not modify other skills"))

        # high: dynamic shell construction
        if (DYNAMIC_SHELL_RE.search(line) or OS_SYSTEM_RE.search(line)) and DYNAMIC_HINT_RE.search(line):
            findings.append(Finding(
                "dynamic_shell", "high", rel, i, sanitize(line),
                "shell=True / os.system with an interpolated string — command injection risk"))

        # medium: curl|sh
        if CURL_PIPE_SH_RE.search(line):
            findings.append(Finding(
                "curl_pipe_sh", "medium", rel, i, sanitize(line),
                "pipes a download straight into a shell — runs unreviewed remote code"))

        # medium: raw eval/exec not already flagged as obfuscated
        if EVAL_RE.search(line) and not (has_decode and has_eval):
            findings.append(Finding(
                "raw_eval_exec", "medium", rel, i, sanitize(line),
                "dynamic code execution — verify the argument is never attacker-influenced"))

    # ---- info tier (context only; baseline-able; off by default) ---------
    if has_network:
        ln = next((i + 1 for i, l in enumerate(lines) if code[i] and NETWORK_RE.search(l)), 1)
        findings.append(Finding("network_egress", "info", rel, ln,
                                sanitize(lines[ln - 1] if ln <= len(lines) else ""),
                                "network egress (normal for many skills)"))
    for i, line in enumerate(lines, 1):
        if code[i - 1] and SECRET_ENV_RE.search(line):
            findings.append(Finding("secret_env_access", "info", rel, i, sanitize(line),
                                    "reads a *_TOKEN/_KEY/_SECRET env var (normal for many skills)"))
            break

    return findings


def scan_skill(skill_dir: Path, root: Path):
    findings = []
    for path, text in iter_text_files(skill_dir):
        rel = str(path.relative_to(root))
        findings.extend(scan_file(rel, text))
    return findings


def discover_skills(target: Path):
    """A single skill (has SKILL.md) → [target]; otherwise treat as a library root."""
    if (target / "SKILL.md").is_file():
        return [target]
    skills = [d for d in sorted(target.iterdir()) if d.is_dir() and (d / "SKILL.md").is_file()]
    return skills


# ----------------------------------------------------------------------------
# Suppressions
# ----------------------------------------------------------------------------

def load_suppressions(path: Path):
    if path and path.is_file():
        try:
            data = json.loads(path.read_text())
            return set(data.get("suppressed", {}).keys())
        except (OSError, ValueError):
            return set()
    return set()


def write_suppressions(path: Path, findings):
    payload = {"suppressed": {f.fingerprint(): {
        "rule": f.rule, "file": f.file, "line": f.line, "reason": "baselined"}
        for f in findings}}
    path.write_text(json.dumps(payload, indent=2) + "\n")


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------

def human_report(results, show_info, show_suppressed):
    out = []
    totals = {k: 0 for k in SEVERITY_ORDER}
    for skill_name, items in results:
        visible = []
        for f, supp in items:
            if f.severity == "info" and not show_info:
                continue
            if supp and not show_suppressed:
                continue
            visible.append((f, supp))
        if not visible:
            out.append(f"  {skill_name}: clean")
            continue
        out.append(f"  {skill_name}:")
        for f, supp in sorted(visible, key=lambda x: -SEVERITY_ORDER[x[0].severity]):
            if not supp:
                totals[f.severity] += 1
            tag = " [suppressed]" if supp else ""
            out.append(f"    [{f.severity.upper():8}] {f.rule}{tag}  {f.file}:{f.line}")
            out.append(f"               {f.note}")
            out.append(f"               > {f.snippet}")
    header = (f"Scanned {len(results)} skill(s).  "
              f"{totals['critical']} critical / {totals['high']} high / "
              f"{totals['medium']} medium / {totals['low']} low"
              + (f" / {totals['info']} info" if show_info else "")
              + " (excludes suppressed).")
    return header + "\n" + "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Deterministic static scanner for skills.")
    ap.add_argument("path", help="a skill directory, or a library root containing skills")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--show-info", action="store_true", help="include the info/context tier")
    ap.add_argument("--show-suppressed", action="store_true", help="include suppressed findings")
    ap.add_argument("--suppressions", help="path to a suppressions JSON file")
    ap.add_argument("--baseline", action="store_true",
                    help="record every current finding as suppressed, then exit 0")
    args = ap.parse_args(argv)

    target = Path(args.path).expanduser().resolve()
    if not target.exists():
        print(f"error: path not found: {target}", file=sys.stderr)
        return 2

    supp_path = Path(args.suppressions).expanduser() if args.suppressions else None
    suppressed_fps = load_suppressions(supp_path) if supp_path else set()

    skills = discover_skills(target)
    if not skills:
        print(f"error: no SKILL.md found at or under {target}", file=sys.stderr)
        return 2

    all_findings = []
    results = []  # (skill_name, [(Finding, suppressed_bool)])
    for skill in skills:
        root = skill.parent
        fs = scan_skill(skill, root)
        all_findings.extend(fs)
        results.append((skill.name, [(f, f.fingerprint() in suppressed_fps) for f in fs]))

    if args.baseline:
        if not supp_path:
            print("error: --baseline requires --suppressions FILE", file=sys.stderr)
            return 2
        write_suppressions(supp_path, all_findings)
        print(f"baselined {len(all_findings)} finding(s) into {supp_path}")
        return 0

    # exit code from non-suppressed, non-info findings
    worst = 0
    for _, items in results:
        for f, supp in items:
            if supp or f.severity == "info":
                continue
            worst = max(worst, SEVERITY_ORDER[f.severity])
    exit_code = 2 if worst >= 3 else (1 if worst >= 1 else 0)

    if args.json:
        payload = {
            "root": str(target),
            "skills_scanned": len(skills),
            "exit_code": exit_code,
            "findings": [f.to_dict(supp) for _, items in results for f, supp in items],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(human_report(results, args.show_info, args.show_suppressed))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
