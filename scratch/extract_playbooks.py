import pprint
import importlib.util
import sys
import re
from unittest.mock import MagicMock

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

for tpl in templates:
    for playbook in tpl.get('playbooks', []):
        flow = playbook.pop('flow_definition', None)
        if flow and 'steps' in flow:
            instructions = []
            for i, step in enumerate(flow['steps']):
                if 'instruction' in step:
                    instructions.append(f"{i+1}. {step['instruction']}")
                elif 'tool_name' in step:
                    instructions.append(f"{i+1}. Execute tool: $tools:{step['tool_name']}")
            playbook['instructions'] = "\n".join(instructions)

unique_playbooks = {}
for tpl in templates:
    for pb in tpl.get('playbooks', []):
        name = pb['name']
        if name not in unique_playbooks:
            unique_playbooks[name] = pb

def make_var_name(name):
    # Remove all non-alphanumeric characters except space
    safe_name = re.sub(r'[^a-zA-Z0-9 ]', '', name)
    return "PB_" + safe_name.upper().strip().replace(" ", "_")

with open("scratch/reusable_playbooks.py", "w") as f:
    f.write("from typing import Any\n\n")
    
    for name, pb in unique_playbooks.items():
        var_name = make_var_name(name)
        f.write(f"{var_name}: dict[str, Any] = {pprint.pformat(pb, sort_dicts=False)}\n\n")
        
    f.write("TEMPLATES: list[dict[str, Any]] = [\n")
    for tpl in templates:
        f.write("    {\n")
        max_keys = list(tpl.keys())
        for key in max_keys:
            value = tpl[key]
            if key == 'playbooks':
                f.write("        'playbooks': [\n")
                for pb in value:
                    var_name = make_var_name(pb['name'])
                    f.write(f"            {var_name},\n")
                f.write("        ],\n")
            else:
                f.write(f"        '{key}': {pprint.pformat(value, sort_dicts=False)},\n")
        f.write("    },\n")
    f.write("]\n")

