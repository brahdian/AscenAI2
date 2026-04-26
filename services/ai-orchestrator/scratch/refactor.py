import re
import os
import glob

def extract_templates():
    templates = {}
    for filepath in sorted(glob.glob("app/services/seed_template_playbooks_*.py")):
        with open(filepath, "r") as f:
            content = f.read()
            
        lines = content.split('\n')
        current_key = None
        current_content = []
        
        for line in lines:
            # Detect start of a template key at exactly 8 spaces
            match = re.match(r'^        "([a-z_]+)":\s*\[$', line)
            if match:
                current_key = match.group(1)
                current_content = []
                continue
                
            # Detect end of a template key array at exactly 8 spaces
            if current_key and re.match(r'^        \],?$', line):
                templates[current_key] = "\n".join(current_content)
                current_key = None
                continue
                
            if current_key:
                current_content.append(line)
                
    return templates

templates = extract_templates()
for k, v in templates.items():
    print(f"Extracted {k} with {len(v)} chars")


# New mappings
mapping_1 = {
    "front_desk_receptionist": ["business_receptionist", "local_business_info", "triage_routing"],
    "inbound_sales_agent": ["sales_assistant", "lead_capture", "quote_generator", "sales_qualifier"],
    "master_scheduler": ["appointment_booking", "appointment_scheduler_pro"]
}

mapping_2 = {
    "order_manager": ["order_taking", "order_support"],
    "support_help_desk": ["customer_support", "technical_support", "it_help_desk"],
    "customer_success_manager": ["customer_success", "follow_up", "strict_workflow"]
}

mapping_3 = {
    "healthcare_receptionist": ["healthcare_receptionist"],
    "real_estate_assistant": ["real_estate_assistant"],
    "legal_intake": ["legal_intake"]
}

mapping_4 = {
    "hr_assistant": ["hr_assistant"],
    "financial_advisor": ["financial_advisor"]
}

header_template = """\"\"\"
Zenith State specific playbook instructions - Part {part}
Variable syntax: $vars:key
\"\"\"
from __future__ import annotations
from typing import Any, Dict, List
from .seed_template_builders import _build_instructions, _create_playbook

def get_playbooks_part_{part}() -> Dict[str, List[Dict[str, Any]]]:
    return {{
"""

footer = """    }
"""

def write_file(part, mapping, filepath):
    with open(filepath, "w") as f:
        f.write(header_template.format(part=part))
        first_key = True
        for new_key, old_keys in mapping.items():
            if not first_key:
                f.write(",\n")
            first_key = False
            
            f.write(f'        "{new_key}": [\n')
            
            combined_playbooks = []
            for old_key in old_keys:
                if old_key in templates:
                    # some playbooks end in a comma, some don't. We will just split by ",\n            _create_playbook"
                    content = templates[old_key]
                    combined_playbooks.append(content)
            
            # Since content is lines of string, we just join them. But wait:
            # We need to make sure there are commas between the playbooks from different old_keys.
            # Usually the last playbook in an array doesn't have a trailing comma in the source code.
            
            fixed_playbooks = []
            for chunk in combined_playbooks:
                # remove any trailing whitespace/newlines
                chunk = chunk.rstrip()
                # if it doesn't end with a comma, add one
                if not chunk.endswith(','):
                    chunk += ','
                fixed_playbooks.append(chunk)
                
            final_content = "\n".join(fixed_playbooks)
            # Remove the very last comma
            final_content = final_content.rstrip(',')
            
            f.write(final_content + "\n")
            f.write('        ]')
            
        f.write("\n" + footer)


write_file(1, mapping_1, "app/services/seed_template_playbooks_1.py")
write_file(2, mapping_2, "app/services/seed_template_playbooks_2.py")
write_file(3, mapping_3, "app/services/seed_template_playbooks_3.py")
write_file(4, mapping_4, "app/services/seed_template_playbooks_4.py")

print("Files generated.")
