import os
import re

services = ["ai-orchestrator", "api-gateway", "mcp-server", "voice-pipeline"]
packages = {}

def parse_req(line):
    # Match package name followed by optional specifiers
    match = re.match(r"^([a-zA-Z0-9\[\]_-]+)(.*)$", line)
    if match:
        name = match.group(1).lower()
        spec = match.group(2).strip()
        return name, spec if spec else None
    return None, None

for svc in services:
    req_path = os.path.join("services", svc, "requirements.txt")
    if os.path.exists(req_path):
        with open(req_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    name, spec = parse_req(line)
                    if name:
                        if name not in packages:
                            packages[name] = set()
                        if spec:
                            packages[name].add(spec)

# Add dev tools
packages["ruff"] = set()
packages["pytest"] = { "==8.3.3" }
packages["pytest-asyncio"] = { "==0.24.0" }

with open("requirements-all.txt", "w") as f:
    for name in sorted(packages.keys()):
        specs = packages[name]
        if not specs:
            f.write(f"{name}\n")
        else:
            # Handle conflicts: if we have multiple, pick one or let pip decide
            # For now, let's just pick the last one in sorted order (usually highest version)
            best_spec = sorted(list(specs))[-1]
            f.write(f"{name}{best_spec}\n")

print(f"Consolidated {len(packages)} unique packages into requirements-all.txt")
