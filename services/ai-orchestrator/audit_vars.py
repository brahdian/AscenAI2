
import re
import ast

def find_vars(content):
    return re.findall(r'\$vars:(\w+)', content)

def audit_templates(file_path):
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Try to find TEMPLATES list using regex and ast (simpler than full parsing)
    match = re.search(r'TEMPLATES: list\[dict\[str, Any\]\] = \[(.*)\]', content, re.DOTALL)
    if not match:
        print("Could not find TEMPLATES list")
        return

    # This is a bit risky but let's try to parse the whole file to get the live dicts
    # Actually, let's just use regex to find each template block
    templates_str = match.group(1)
    # Split by template dicts (roughly)
    template_blocks = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', templates_str)

    # Re-reading: SHARED_VARIABLES
    shared_vars_match = re.search(r'SHARED_VARIABLES = \{(.*?)\}', content, re.DOTALL)
    shared_vars = []
    if shared_vars_match:
        shared_vars = re.findall(r'"(\w+)":', shared_vars_match.group(1))
    
    print(f"Shared Variables: {shared_vars}")

    # Vertical-specific audit
    for i, block in enumerate(template_blocks):
        name_match = re.search(r'"name": "(.*?)"', block)
        template_name = name_match.group(1) if name_match else f"Template {i}"
        
        # Find all $vars: references in this block
        refs = set(find_vars(block))
        
        # Find defined variables (keys)
        # 1. SHARED_VARIABLES references
        shared_refs = re.findall(r'SHARED_VARIABLES\["(\w+)"\]', block)
        # 2. Local variable definitions
        local_defs = re.findall(r'"key": "(\w+)"', block)
        # (Exclude the template key itself from local_defs)
        template_key_match = re.search(r'"key": "(\w+)"', block)
        template_key = template_key_match.group(1) if template_key_match else None
        defined_vars = set(shared_refs) | (set(local_defs) - {template_key})
        
        # Also include business_hours and location as they are often in shared_vars but templates might use them
        
        orphaned = refs - defined_vars
        if orphaned:
            print(f"Template '{template_name}' has orphaned variables: {orphaned}")
            print(f"  Defined: {defined_vars}")

if __name__ == "__main__":
    audit_templates("/Users/visvasis/Home/Jamvant/ascenai/services/ai-orchestrator/app/services/seed_templates.py")
