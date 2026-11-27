#!/usr/bin/env python3
"""
Transcribe a single YouTube video.

Primary method : youtube-transcript-api (public caption track, no auth).
Fallback method: Supadata universal transcript API (x-api-key header).

The script prints a single JSON object to stdout and nothing else, so the
caller can parse it directly:

    {"ok": true,  "method": "youtube-transcript-api", "lang": "en", "text": "..."}
    {"ok": true,  "method": "supadata",              "lang": "en", "text": "..."}
    {"ok": false, "error": "youtube-transcript-api: ... | supadata: ..."}

Exit code is 0 on success, 1 on failure (the JSON is printed either way).

Usage:
    python3 transcribe.py --url "https://www.youtube.com/watch?v=VIDEO_ID" \
        --lang en --supadata-token "$SUPADATA_TOKEN"
    python3 transcribe.py --video-id VIDEO_ID --supadata-token "$SUPADATA_TOKEN"

Dependencies:
    - Standard library only is required (urllib).
    - youtube-transcript-api is used if importable; if it is missing or blocked
      (e.g. datacenter IP bans), the script silently falls back to Supadata.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SUPADATA_BASE = "https://api.supadata.ai/v1/transcript"


def extract_video_id(url_or_id):
    """Pull a bare 11-char video id out of any YouTube URL, or pass through an id."""
    if not url_or_id:
        return None
    s = url_or_id.strip()
    if "youtube.com" in s or "youtu.be" in s:
        try:
            p = urllib.parse.urlparse(s)
            if p.hostname and "youtu.be" in p.hostname:
                vid = p.path.lstrip("/").split("/")[0]
                return vid or None
            q = urllib.parse.parse_qs(p.query)
            if "v" in q and q["v"]:
                return q["v"][0]
            # /shorts/<id> or /embed/<id>
            parts = [seg for seg in p.path.split("/") if seg]
            if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live"):
                return parts[1]
        except Exception:
            pass
    return s  # assume it is already an id


# --------------------------------------------------------------------------- #
# Method 1: youtube-transcript-api
# --------------------------------------------------------------------------- #
def try_youtube_transcript_api(video_id, lang):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception as e:  # not installed / import error
        return None, "library unavailable ({})".format(e)

    langs = [lang] if lang else ["en"]

    # New instance API (youtube-transcript-api >= 1.0)
    try:
        api = YouTubeTranscriptApi()
        fetched = None
        try:
            fetched = api.fetch(video_id, languages=langs)
        except Exception:
            # Requested language missing -> take the first available transcript.
            try:
                transcript_list = api.list(video_id)
                first = next(iter(transcript_list), None)
                if first is not None:
                    fetched = first.fetch()
            except Exception as e_list:
                return None, "{}: {}".format(type(e_list).__name__, e_list)
        if fetched is None:
            return None, "no transcript available"
        snippets = list(fetched)
        text = " ".join(getattr(s, "text", "") for s in snippets).strip()
        used_lang = getattr(fetched, "language_code", "") or (langs[0] if langs else "")
        if text:
            return {"text": text, "lang": used_lang}, None
        return None, "empty transcript"
    except Exception as e_new:
        # Old static API (youtube-transcript-api < 1.0)
        try:
            from youtube_transcript_api import YouTubeTranscriptApi as YTA
            data = YTA.get_transcript(video_id, languages=langs)
            text = " ".join(seg.get("text", "") for seg in data).strip()
            if text:
                return {"text": text, "lang": langs[0] if langs else ""}, None
            return None, "empty transcript"
        except Exception:
            return None, "{}: {}".format(type(e_new).__name__, e_new)


# --------------------------------------------------------------------------- #
# Method 2: Supadata
# --------------------------------------------------------------------------- #
def _supadata_text(data):
    """content can be a plain string (text=true) or a list of timed segments."""
    if not isinstance(data, dict):
        return ""
    c = data.get("content")
    if isinstance(c, str):
        return c.strip()
    if isinstance(c, list):
        return " ".join(
            seg.get("text", "") for seg in c if isinstance(seg, dict)
        ).strip()
    t = data.get("transcript")
    if isinstance(t, str):
        return t.strip()
    return ""


def _supadata_get(url, token, timeout=120):
    req = urllib.request.Request(url, headers={"x-api-key": token})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def _poll_supadata_job(job_id, token, lang, timeout=180):
    url = "{}/{}".format(SUPADATA_BASE, urllib.parse.quote(job_id))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            _, body = _supadata_get(url, token, timeout=60)
        except urllib.error.HTTPError as e:
            return None, "supadata job HTTP {}".format(e.code)
        except Exception as e:
            return None, "supadata job request failed: {}".format(e)
        try:
            data = json.loads(body)
        except Exception:
            return None, "supadata job: non-JSON response"
        status = str(data.get("status", "")).lower()
        if status in ("completed", "complete", "done", "success"):
            text = _supadata_text(data)
            if text:
                return {"text": text, "lang": data.get("lang", lang or "")}, None
            return None, "supadata job: empty content"
        if status in ("failed", "error"):
            return None, "supadata job failed: {}".format(
                data.get("error") or data.get("message") or "unknown"
            )
        time.sleep(3)
    return None, "supadata job: timed out"


def try_supadata(url, lang, token):
    if not token:
        return None, "no token provided"
    # mode=native fetches only an existing caption track and never triggers paid
    # Whisper AI generation. Captionless videos return 206 (handled as a failure).
    params = {"url": url, "text": "true", "mode": "native"}
    if lang:
        params["lang"] = lang
    full = SUPADATA_BASE + "?" + urllib.parse.urlencode(params)
    try:
        status, body = _supadata_get(full, token, timeout=120)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            j = json.loads(e.read().decode("utf-8", "replace"))
            detail = j.get("message") or j.get("error") or ""
        except Exception:
            pass
        # 404 = missing/private, 403 = restricted/auth required
        return None, "HTTP {}{}".format(e.code, ": " + detail if detail else "")
    except Exception as e:
        return None, "request failed: {}".format(e)

    if status == 206:
        return None, "transcript unavailable (206)"

    try:
        data = json.loads(body)
    except Exception:
        return None, "non-JSON response"

    if status == 202 or (isinstance(data, dict) and data.get("jobId") and not data.get("content")):
        return _poll_supadata_job(data.get("jobId", ""), token, lang)

    text = _supadata_text(data)
    if text:
        return {"text": text, "lang": data.get("lang", lang or "")}, None
    return None, "empty content"


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Transcribe a single YouTube video.")
    ap.add_argument("--video-id", default="")
    ap.add_argument("--url", default="")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--supadata-token", default="")
    args = ap.parse_args()

    vid = args.video_id.strip() or extract_video_id(args.url)
    if not vid:
        print(json.dumps({"ok": False, "error": "no --video-id or --url provided"}))
        sys.exit(1)

    url = args.url.strip() or "https://www.youtube.com/watch?v={}".format(vid)
    lang = args.lang or "en"

    res, err1 = try_youtube_transcript_api(vid, lang)
    if res:
        print(json.dumps({
            "ok": True, "method": "youtube-transcript-api",
            "lang": res.get("lang", ""), "text": res["text"],
        }))
        sys.exit(0)

    res2, err2 = try_supadata(url, lang, args.supadata_token)
    if res2:
        print(json.dumps({
            "ok": True, "method": "supadata",
            "lang": res2.get("lang", ""), "text": res2["text"],
        }))
        sys.exit(0)

    print(json.dumps({
        "ok": False,
        "error": "youtube-transcript-api: {} | supadata: {}".format(err1, err2),
    }))
    sys.exit(1)


if __name__ == "__main__":
    main()
