# ToolMux Internal-to-Public Sync & Sanitization

**Date:** 2026-04-05
**Status:** Approved
**Scope:** Sync internal repo (code.amazon.com v2.2.1) to public GitHub (v1.2.1), stripping all Amazon-specific content

---

## Problem

The internal Amazon repo (`code.amazon.com/packages/ToolMux`) is at **v2.2.1** with a major FastMCP 3.x rewrite, while the public GitHub repo (`github.com/subnetangel/ToolMux`) is stuck at **v1.2.1** with the old hand-rolled JSON-RPC implementation. The internal repo contains Amazon-specific references (internal URLs, tooling, credentials, server examples) that must be stripped for open-source publication.

## Approach: Fresh Overlay

Copy all internal files into the GitHub clone, delete internal-only files, sanitize remaining files, commit as a single update. No git merge — the histories diverged architecturally and a merge would create unresolvable conflicts.

## Source Repos

| Repo | Location | Version |
|------|----------|---------|
| Internal | `/tmp/toolmux-internal` (cloned from `ssh://git.amazon.com/pkg/ToolMux`) | 2.2.1 |
| Public | `/tmp/toolmux-github` (cloned from `github.com/subnetangel/ToolMux`) | 1.2.1 |

---

## Step 1: Copy Internal Files to GitHub Clone

Copy the entire internal repo contents (excluding `.git/`) into the GitHub clone, overwriting existing files.

**Command:**
```bash
rsync -av --exclude='.git' /tmp/toolmux-internal/ /tmp/toolmux-github/
```

---

## Step 2: Delete Internal-Only Files

These files exist solely for Amazon internal distribution and have no public value:

| File | Reason |
|------|--------|
| `scripts/publish.sh` | S3-based internal publish pipeline (account 340458173771, isengard, aws-support registry) |
| `docs/PUBLISHING.md` | Full internal publishing guide with S3 buckets, AIM registry, toolbox-bundler |
| `tool-metadata/alinux.json` | Builder Toolbox bundler metadata |
| `tool-metadata/osx.json` | Builder Toolbox bundler metadata |
| `tool-metadata/` (directory) | Entire directory is internal-only |
| `toolmux.spec` | PyInstaller spec for internal binary distribution via Builder Toolbox |
| `.kiro/specs/toolmux-v2-fastmcp-rewrite/` | Internal Kiro design specs (requirements.md, design.md, tasks.md) |
| `toolmux/examples/example_mcp.json` | Contains `git.amazon.com`, `amzn-mcp`, `user@amazon.com`, K2Dante paths |
| `toolmux/examples/q-cli-toolmux-config.json` | Identical to example_mcp.json — same Amazon internal servers |
| `Config` | Empty/unused internal file |
| `ToolMux.code-workspace` | Personal VS Code workspace file |
| `toolmux_entry.py` | PyInstaller entry point for internal binary (not needed for pip/uvx install) |

---

## Step 3: Sanitize `pyproject.toml`

**Changes:**
```
[project.urls]
- Homepage = "https://code.amazon.com/packages/ToolMux/trees/mainline"
- Repository = "https://code.amazon.com/packages/ToolMux"
- Issues = "https://code.amazon.com/packages/ToolMux/issues"
+ Homepage = "https://github.com/subnetangel/ToolMux"
+ Repository = "https://github.com/subnetangel/ToolMux"
+ Issues = "https://github.com/subnetangel/ToolMux/issues"
```

No other changes — version, deps, metadata all correct for public use.

---

## Step 4: Sanitize `toolmux/main.py`

Two targeted changes:

### 4a. CLI epilog URL (line ~1667)
```python
# Before:
epilog="For more information, visit: https://code.amazon.com/packages/ToolMux/trees/mainline"
# After:
epilog="For more information, visit: https://github.com/subnetangel/ToolMux"
```

### 4b. Comment about Amazon internal (line ~1427)
```python
# Before:
    config for a server. Supports both Amazon internal (mcp-registry/AIM)
    and open source (Claude Desktop, Cursor, mcp.json) config formats.
# After:
    config for a server. Supports mcp-registry bundles and standard
    MCP config files (Claude Desktop, Cursor, XDG mcp.json).
```

### 4c. Bundle resolution paths — keep as-is
The `smithy-mcp` and `.aim/bundles` paths are functional config discovery locations used by the open-source mcp-registry tooling, not Amazon-proprietary. The code works correctly for any user who has these directories. Keep the paths, just fix the docstring.

---

## Step 5: Sanitize README.md

### 5a. Installation section — replace entirely
```markdown
## Installation

```bash
# Via PyPI
pip install toolmux

# Via uvx (recommended, no install needed)
uvx toolmux

# From source
git clone https://github.com/subnetangel/ToolMux.git
cd ToolMux
pip install -e .
```
```

### 5b. Remove "Use with Kiro CLI / AIM" subsection
Replace with a generic "Use with any MCP client" section showing the standard `mcpServers` config pattern.

### 5c. Self-Healing Bundle Resolution section
- Remove "smithy-mcp bundles" and "AIM MCP bundles" labels
- Replace with generic labels: "mcp-registry bundles (`~/.config/smithy-mcp/bundles/`)" and "User bundles (`~/.aim/bundles/`)"

### 5d. Publishing section — remove entirely
Delete the entire "Publishing" section (ada credentials, publish.sh, Builder Toolbox verification). Not relevant for public repo.

### 5e. Config file discovery — update path 3
```
3. `~/shared/toolmux/mcp.json` (AgentSpaces — persists across sessions)
```
Change "AgentSpaces" to "shared environments" since AgentSpaces is an Amazon internal product.

---

## Step 6: Sanitize CHANGELOG.md

### Changes:
- **v2.2.0**: Remove "(e.g., aws-support-troubleshooting-mcp's Redis `evalsha` error)" — replace with "(e.g., a crashing backend server)". Remove "AIM bundles" → "mcp-registry bundles". Remove "SAML-auth servers like `slack-mcp`" → "authenticated servers".
- **v2.1.0 Publishing section**: Delete the entire "Publishing" subsection (Builder Toolbox, macOS binary pending).
- **v2.0.5 Publishing section**: Delete (S3 bucket, registry, publish script details). Remove "AIM MCP config" from Changed section.
- **v1.1.3**: Remove "Updated all repository references to point to Amazon internal repository" and related items — replace with generic "Updated repository URLs".
- Remove all references to: `ada credentials`, `isengard`, account IDs, `aws-support` registry, `s3://buildertoolbox-*`.

---

## Step 7: Sanitize Remaining Docs

### `docs/ARCHITECTURE.md`
- Remove the Mermaid diagram nodes referencing S3/Builder Toolbox/AIM
- Replace with generic "Distribution" section (PyPI, uvx)

### `docs/DEPLOYMENT_PLAN.md`
- Remove "Option 2: Amazon Internal Development Install" section
- Remove "Option 3: Amazon Internal Distribution" section
- Remove all `code.amazon.com` URLs and `ada credentials` commands
- Keep Option 1 (PyPI/uvx) as the primary install method

### `docs/DEVELOPER_GUIDE.md`
- Remove infrastructure table (Repository ssh://git.amazon.com, S3 Bucket, Registry, AIM MCP ID)
- Update repository URL to GitHub

### `docs/USER_GUIDE.md`
- Replace Builder Toolbox / AIM install instructions with pip/uvx
- Replace troubleshooting entry for `toolbox install` with `pip install`

### `docs/PUBLICATION_REPORT.md`
- Update repository URL from code.amazon.com to GitHub

### `.kiro/mcp.json`
- Remove `--registry aws-support` from description string
- Keep the Kiro integration config structure (Kiro is becoming a public product)

### `CLAUDE.md`
- Scan for any internal references and update

---

## Step 8: Run Tests

```bash
cd /tmp/toolmux-github
pip install -e ".[dev]"
python3 -m pytest tests/ -v
```

All 107 tests should pass. The sanitization touches only URLs, comments, docs, and config examples — no functional code changes.

---

## Step 9: Commit and Push

```bash
cd /tmp/toolmux-github
git add -A
git commit -m "Update to v2.2.1: FastMCP 3.x rewrite with three operating modes

Major update syncing public repo from v1.2.1 to v2.2.1:
- FastMCP 3.x foundation replacing hand-rolled JSON-RPC
- Three operating modes: Gateway (default), Meta, Proxy
- Smart description/schema condensation for token optimization
- Self-healing bundle resolution
- Parallel backend initialization
- LLM-powered description optimization
- 107 tests, all passing"
git push origin main
```

---

## What Is NOT Changed

- **All functional code** in `toolmux/main.py` (except 2 string literals)
- **All test files** — copied as-is
- **Bundle resolution logic** — the `smithy-mcp` and `.aim/bundles` paths are generic
- **MIT License** — unchanged
- **Author/email** — unchanged (JP Ruiz / juanpa.ruiz@gmail.com)
- **Generic example configs** — filesystem.json, brave-search.json, mixed-servers.json, http-servers.json, sqlite.json, kiro-integration.json

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Tests break after sanitization | Only docs/URLs changed, not functional code. Run tests before push. |
| Missed Amazon reference | Grep for `amazon`, `aws-support`, `code.amazon`, `isengard`, `ada credentials`, `toolbox install`, `AIM`, `builder-mcp` after sanitization |
| PyPI version conflict | Current PyPI version is 1.2.1. Publishing 2.2.1 is a clean upgrade. |
| Bundle resolution breaks | Paths are kept, only comments changed. Tests cover this. |
