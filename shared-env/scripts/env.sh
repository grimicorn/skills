#!/usr/bin/env bash
# shared-env constants: the single source of truth for paths, repo, and URLs.
# PUBLIC TEMPLATE: replace the placeholder values with your own.
#
# SOURCE this file, don't execute it:
#
#   SKILLS_ROOT="$(ls -d /mnt/skills/user 2>/dev/null || ls -d /sessions/*/mnt/.claude/skills 2>/dev/null | head -1)"
#   . "$SKILLS_ROOT/shared-env/scripts/env.sh"
#
# Secrets do NOT go here. Skills reference secret names only (e.g. GITHUB_TOKEN);
# load the values from your secret manager (dotenvx, 1Password CLI, ...) at run time.

# --- Obsidian vault -----------------------------------------------------------
# Mac filesystem path first; fall back to the Cowork bash sandbox mount.
OBSIDIAN_VAULT_MAC="${OBSIDIAN_VAULT_MAC:-$HOME/Library/Mobile Documents/<obsidian-icloud-folder>/Documents/Vault/Claude}"
OBSIDIAN_VAULT="$OBSIDIAN_VAULT_MAC"
if [ ! -d "$OBSIDIAN_VAULT" ]; then
  OBSIDIAN_VAULT="$(ls -d /sessions/*/mnt/Claude 2>/dev/null | head -1)"
fi

# --- Blog repo ----------------------------------------------------------------
BLOG_GITHUB_REPO="your-org/your-blog"
BLOG_GITHUB_BRANCH="main"
BLOG_LOCAL_REPO="$HOME/Development/your-blog"

BLOG_POSTS_PATH="content/posts"
BLOG_DATA_PATH="data"
BLOG_IMAGES_PATH="public/images"

# --- Site URLs ----------------------------------------------------------------
BLOG_URL="https://example.com"
BLOG_POSTS_URL="$BLOG_URL/posts"

# --- Derived bases (build repo URLs from these; never hardcode a raw URL) ------
BLOG_RAW_BASE="https://raw.githubusercontent.com/$BLOG_GITHUB_REPO/$BLOG_GITHUB_BRANCH"

# --- Content ------------------------------------------------------------------
ARTICLE_TOPICS="development, ai"

export OBSIDIAN_VAULT OBSIDIAN_VAULT_MAC \
       BLOG_GITHUB_REPO BLOG_GITHUB_BRANCH BLOG_LOCAL_REPO \
       BLOG_POSTS_PATH BLOG_DATA_PATH BLOG_IMAGES_PATH \
       BLOG_URL BLOG_POSTS_URL BLOG_RAW_BASE \
       ARTICLE_TOPICS

if [ -z "$OBSIDIAN_VAULT" ] || [ ! -d "$OBSIDIAN_VAULT" ]; then
  echo "shared-env: WARNING: Obsidian vault not resolved. Do not write to a stray path." >&2
fi
