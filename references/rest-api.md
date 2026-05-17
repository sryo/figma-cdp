# Figma REST API reference

Read-only file operations and the comment workflow, without a browser session. Supplementary to the Plugin API: most figma-cdp work happens via `agent-browser` evals. Reach for REST when you need image rendering, comments, version history, or when no browser is available.

For where to use REST inside a workflow, see:
- `references/reading.md` → Pre-flight workflow → Via REST API
- `references/copy.md` → Designer-agent feedback loop (comment posting/polling)

## Auth setup

1. Generate a **personal access token** at `https://www.figma.com/developers/api#access-tokens`.
2. Store it:
   ```bash
   export FIGMA_TOKEN="figd_..."
   ```

## Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/files/:key` | Full file tree (pages, frames, nodes) |
| `GET /v1/files/:key/nodes?ids=X,Y` | Specific node subtrees |
| `GET /v1/images/:key?ids=X,Y&format=png` | Render nodes as images |
| `GET /v1/files/:key/components` | Published components |
| `GET /v1/files/:key/styles` | Published styles |
| `GET /v1/files/:key/versions` | Version history |
| `GET /v1/files/:key/comments` | List comments |
| `POST /v1/files/:key/comments` | Add a comment |
| `DELETE /v1/files/:key/comments/:id` | Delete a comment |
| `POST\|PUT /v1/dev_resources` | Create / update dev resource |

> **Variables REST endpoint** requires Figma Enterprise: not available on free/pro plans. Use the Plugin API `figma.variables.*` instead.

## Helper script

Write `/tmp/figma_api.py` (symmetric with `figma_run.py`; no permission prompts):

```python
#!/usr/bin/env python3
"""Minimal Figma REST API helper. Usage: python3 /tmp/figma_api.py <endpoint> [--raw]"""
import sys, os, json, urllib.request, urllib.error

TOKEN = os.environ.get("FIGMA_TOKEN", "")
if not TOKEN:
    print("ERROR: Set FIGMA_TOKEN env var", file=sys.stderr); sys.exit(1)

args = [a for a in sys.argv[1:] if a != "--raw"]
raw = "--raw" in sys.argv
if not args:
    print("Usage: python3 /tmp/figma_api.py <endpoint> [--raw]", file=sys.stderr); sys.exit(1)

url = f"https://api.figma.com/{args[0].lstrip('/')}"
req = urllib.request.Request(url, headers={"X-Figma-Token": TOKEN})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()}", file=sys.stderr); sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr); sys.exit(1)

print(json.dumps(data) if raw else json.dumps(data, indent=2))
```

## Examples

```bash
# Read file structure
python3 /tmp/figma_api.py "v1/files/ABC123xyz"

# Inspect specific nodes
python3 /tmp/figma_api.py "v1/files/ABC123xyz/nodes?ids=0:1,1:2"

# Render a node as PNG (returns URLs to rendered images)
python3 /tmp/figma_api.py "v1/images/ABC123xyz?ids=1:2&format=png&scale=2"

# List comments
python3 /tmp/figma_api.py "v1/files/ABC123xyz/comments?as_md=true"

# Version history
python3 /tmp/figma_api.py "v1/files/ABC123xyz/versions"
```

## Comment operations

The `figma_api.py` helper above only supports GET. For POST/DELETE (comments, dev resources), use `curl`:

```bash
# Post a comment pinned to a node
curl -s -X POST \
  -H "X-Figma-Token: $FIGMA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Suggestion: more action-oriented heading",
       "client_meta": {"node_id": "1:2", "node_offset": {"x": 0, "y": 0}}}' \
  "https://api.figma.com/v1/files/$FIGMA_FILE_KEY/comments"

# Reply to a comment (threading)
curl -s -X POST \
  -H "X-Figma-Token: $FIGMA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Updated: how about: Ship faster with confidence?",
       "comment_id": "PARENT_COMMENT_ID"}' \
  "https://api.figma.com/v1/files/$FIGMA_FILE_KEY/comments"

# Delete a comment
curl -s -X DELETE \
  -H "X-Figma-Token: $FIGMA_TOKEN" \
  "https://api.figma.com/v1/files/$FIGMA_FILE_KEY/comments/COMMENT_ID"
```

> **`resolved_at` is read-only**: there's no API to resolve or unresolve comments. Only designers can resolve in the Figma UI.

## Rate limits and staleness

- **30 requests/minute**: batch node IDs into single calls where possible.
- REST reads may **lag a few seconds** behind Plugin API writes. After mutations, use Plugin API `exportAsync` for immediate verification instead of polling REST.
