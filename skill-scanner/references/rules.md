# Scanner rule catalogue

Each rule is pure pattern matching over text files. Severity drives the exit code
(critical/high → 2, medium/low → 1, info → 0). "Tuned for the user's library" notes
explain why a rule stays quiet on a legitimate skill set.

In markdown/`.txt`, the code-pattern rules below only apply **inside fenced code
blocks**. Prose is checked only for `hidden_unicode` and `injection_phrasing`.
This is deliberate: a markdown link or blockquote pointing at another skill must
not read as a shell redirect or a write.

## critical

### hidden_unicode
Any invisible or directional-control codepoint (Unicode category `Cf`/`Co`, plus
`U+FEFF`) anywhere in any line. Covers zero-width space/joiner family and bidi
overrides/isolates — the "Trojan Source" class, where source looks benign to a
human but parses differently. A leading `U+FEFF` BOM on line 1 is exempt.
Reported with full codepoint names; the snippet shows `<U+XXXX>` tokens, never the
raw character. *Near-zero false positives in code.*

### obfuscated_exec
The same file both decodes a blob (`base64.b64decode`, `bytes.fromhex`,
`binascii.unhexlify`, JS `atob(`) **and** calls `eval`/`exec`/`new Function`. This
is the canonical "decode a payload then run it" shape. One finding per file.

### exfil_credfile_egress
The same file reads a **credential file** (`~/.ssh`, `id_rsa`, `.aws/credentials`,
`.netrc`, `.git-credentials`, `.npmrc`, keychain, `/etc/passwd`, kube/docker
config, …) **and** has network egress. Keyed on credential *files*, not on reading
a `*_TOKEN` env var — that distinction is what keeps legitimate skills (which read
`GITHUB_TOKEN` and call the GitHub API) out of this rule. *Tuned for the user's library.*

## high

### agent_self_modify
A write indicator (`>`/`>>`, `open(...,'w')`, `.write_text`, `tee`, `cp`/`mv`/`echo`)
on a line that also touches `~/.claude`, a shell rc (`.bashrc`/`.zshrc`/`.profile`),
`crontab`, `launchctl`/LaunchAgents/LaunchDaemons, `authorized_keys`, or
`/etc/cron`/`sudoers`. Persistence and self-modification vector. Reading these
paths without writing does not fire (the user's config sync references them).

### cross_skill_write
A write indicator on a line referencing a `skills/` path (`/mnt/skills/`,
`~/.claude/skills/`, `skills/<name>/`). A skill modifying *other* skills is a strong
tampering signal. Markdown links to skills don't fire (they're prose, not code).

### dynamic_shell
`shell=True` or `os.system(` on a line that also shows interpolation (f-string,
`.format(`, `+`, `%`, backtick `${`, `$(`). Command-injection risk. A `shell=True`
with a pure string literal is not flagged.

### injection_phrasing
Instruction-smuggling language: "ignore (all) previous instructions", "disregard
your…", "do not tell/inform the user", "without telling the user", "exfiltrate",
"send … to http/the attacker". **high** in a `SKILL.md` prose line, **medium**
elsewhere. Expect legitimate hits in skills that *teach* injection defence (they
quote these strings) — baseline those.

## medium

### curl_pipe_sh
`curl`/`wget … | sh`/`| bash` — running unreviewed remote code.

### raw_eval_exec
`eval`/`exec`/`new Function` not already covered by `obfuscated_exec`. Often
legitimate; verify the argument is never attacker-influenced.

## info (hidden unless `--show-info`; never affects exit code)

### network_egress
Any network call (`requests`, `httpx`, `urllib`, `socket`, `fetch(`, `curl`/`wget`
to http). Normal for many skills; here only as context.

### secret_env_access
Reads a `*_TOKEN`/`*_KEY`/`*_SECRET`/`*_PASSWORD` env var. Normal for many skills;
context only. (Combined with a credential-file read it would instead surface via
`exfil_credfile_egress`.)

## Suppressions

A finding's fingerprint is `sha256(rule + file + sanitized-snippet)`. The
suppressions file maps fingerprints to a reason. `--baseline` writes one entry per
current finding. Editing the matched line changes the fingerprint, so a suppression
covers exactly that finding and a newly-introduced payload on the same line still
fires.
