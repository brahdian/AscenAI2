import sys
from unittest.mock import MagicMock
import importlib.util

sys.modules['app.core.database'] = MagicMock()
sys.modules['app.models.template'] = MagicMock()
sys.modules['structlog'] = MagicMock()
sys.modules['sqlalchemy.ext.asyncio'] = MagicMock()
sys.modules['sqlalchemy'] = MagicMock()
sys.modules['sqlalchemy.dialects.postgresql'] = MagicMock()

spec = importlib.util.spec_from_file_location("seed", "scratch/seed_updated.py")
seed_file = importlib.util.module_from_spec(spec)
sys.modules["seed"] = seed_file
spec.loader.exec_module(seed_file)

templates = seed_file.TEMPLATES

import json

for tpl in templates:
    for playbook in tpl.get('playbooks', []):
        flow = playbook.pop('flow_definition', None)
        if flow and 'steps' in flow:
            instructions = []
            for i, step in enumerate(flow['steps']):
                if 'instruction' in step:
                    instructions.append(f"{i+1}. {step['instruction']}")
                elif 'tool_name' in step:
                    instructions.append(f"{i+1}. Execute tool: {step['tool_name']}")
            playbook['instructions'] = "\n".join(instructions)

with open("scratch/final_templates.py", "w") as f:
    f.write("from typing import Any\n\nTEMPLATES: list[dict[str, Any]] = [\n")
    for tpl in templates:
        f.write("    {\n")
        max_keys = list(tpl.keys())
        for key in max_keys:
            value = tpl[key]
            if key == 'playbooks':
                f.write("        'playbooks': [\n")
                for pb in value:
                    f.write("            {\n")
                    for pb_k, pb_v in pb.items():
                        if isinstance(pb_v, str) and '\n' in pb_v:
                            f.write(f"                '{pb_k}': \"\"\"{pb_v}\"\"\",\n")
                        else:
                            f.write(f"                '{pb_k}': {repr(pb_v)},\n")
                    f.write("            },\n")
                f.write("        ],\n")
            elif isinstance(value, str) and '\n' in value:
                f.write(f"        '{key}': \"\"\"{value}\"\"\",\n")
            else:
                f.write(f"        '{key}': {repr(value)},\n")
        f.write("    },\n")
    f.write("]\n")
