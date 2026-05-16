# Figma REST API

Read-only operations without a browser session. The REST API provides read access to any file you have permission to view.

## Auth Setup
1. Go to `https://www.figma.com/developers/api#access-tokens` and generate a **personal access token**.
2. Store it as an environment variable:
   ```bash
   export FIGMA_TOKEN="figd_..."
   ```

## Read Endpoints
| Endpoint | Purpose |
|----------|---------|
| `GET /v1/files/:key` | Full file tree (pages, frames, nodes) |
| `GET /v1/files/:key/nodes?ids=X,Y` | Specific node subtrees |
| `GET /v1/images/:key?ids=X,Y&format=png` | Render nodes as images |
| `GET /v1/files/:key/components` | Published components |
| `GET /v1/files/:key/styles` | Published styles |
| `GET /v1/files/:key/versions` | Version history |

## Write Endpoints (limited)
| Endpoint | Purpose |
|----------|---------|
| `POST /v1/files/:key/comments` | Add a comment |
| `POST /v1/dev_resources` | Create dev resource |
| `PUT /v1/dev_resources` | Update dev resource |

> **Variables REST endpoint** requires Figma Enterprise — not available on free/pro plans. Use the Plugin API `figma.variables.*` instead.

## REST API Helper Script
Create `/tmp/figma_api.py` for convenient REST calls:
```python
#!/usr/bin/env python3
"""Minimal Figma REST API helper. Usage: python3 /tmp/figma_api.py <endpoint> [--raw]"""
import sys, os, json, urllib.request, urllib.error

TOKEN = os.environ.get("FIGMA_TOKEN", "")
if not TOKEN:
    print("ERROR: Set FIGMA_TOKEN env var", file=sys.stderr); sys.exit(1)
if len(sys.argv) < 2:
    print("Usage: python3 /tmp/figma_api.py <endpoint> [--raw]", file=sys.stderr); sys.exit(1)

endpoint = sys.argv[1].lstrip("/")
url = f"https://api.figma.com/{endpoint}"
req = urllib.request.Request(url, headers={"X-Figma-Token": TOKEN})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"HTTP {e.code}: {body}", file=sys.stderr); sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr); sys.exit(1)

if "--raw" in sys.argv:
    print(json.dumps(data))
else:
    print(json.dumps(data, indent=2))
```
Example usage:
```bash
# Read file structure
python3 /tmp/figma_api.py "v1/files/ABC123xyz"

# Inspect specific nodes
python3 /tmp/figma_api.py "v1/files/ABC123xyz/nodes?ids=0:1,1:2"

# Render a node as PNG
python3 /tmp/figma_api.py "v1/images/ABC123xyz?ids=1:2&format=png&scale=2"
```

## Rate Limits & Staleness
- **30 requests/minute** for most endpoints — batch node IDs into single calls where possible.
- REST reads may **lag a few seconds** behind Plugin API writes. After mutations, wait briefly or use Plugin API `exportAsync` for immediate verification.
