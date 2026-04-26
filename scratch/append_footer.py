import re

with open("scratch/9b24899_seed.py", "r") as f:
    text = f.read()

footer = text[text.find("async def seed_templates"):]
# Replace "flow_definition": pb.get("flow_definition", {}) with "instructions": pb.get("instructions", "")
footer = footer.replace(
    '"flow_definition": pb.get("flow_definition", {}),',
    '"instructions": pb.get("instructions", ""),'
)

with open("services/ai-orchestrator/app/services/seed_templates.py", "a") as f:
    f.write(footer)

