
import json
import re

file_path = "/Users/visvasis/Home/Jamvant/AscenAI/services/ai-orchestrator/app/services/seed_templates.py"

with open(file_path, 'r') as f:
    content = f.read()

# Try to extract the TEMPLATES list from the python file
# This is a bit hacky but should work if we find the start and end of the list
templates_match = re.search(r"TEMPLATES = \[(.*)\]\s+async def seed_templates", content, re.DOTALL)
if not templates_match:
    print("Could not find TEMPLATES list")
    exit(1)

# We can't easily eval the whole list because of comments and str concatenation
# Let's find playbooks using regex
playbook_matches = re.finditer(r"\{\s*\"name\":\s*\"(?P<name>[^\"]+)\",\s*\"description\":\s*\"(?P<description>[^\"]+)\",.*?\"flow_definition\":\s*\{\s*\"steps\":\s*\[\s*\{\s*\"id\":\s*\"(?P<step_id>[^\"]+)\",\s*\"type\":\s*\"(?P<step_type>[^\"]+)\",\s*\"instruction\":\s*\"(?P<instruction>[^\"]+)\"", content, re.DOTALL)

for match in playbook_matches:
    desc = match.group('description').strip().lower()
    instr = match.group('instruction').strip().lower()
    
    # Check if they are identical or if instruction starts with description
    if desc == instr or instr.startswith(desc):
        print(f"Match found in Playbook: {match.group('name')}")
        print(f"Description: {match.group('description')}")
        print(f"Instruction: {match.group('instruction')}")
        print("-" * 20)
