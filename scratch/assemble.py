import os

def assemble():
    with open("services/ai-orchestrator/app/services/seed_templates.py", "r") as f:
        lines = f.readlines()
        
    header = lines[:26]
    footer = lines[2703:]
    
    # Fix the footer to use instructions instead of flow_definition
    new_footer = []
    for line in footer:
        if '"flow_definition": pb.get("flow_definition", {}),' in line:
            new_footer.append('                        "instructions": pb.get("instructions", ""),\n')
        else:
            new_footer.append(line)
            
    with open("scratch/reusable_playbooks.py", "r") as f:
        playbooks = f.read()
        
    with open("services/ai-orchestrator/app/services/seed_templates.py", "w") as f:
        f.writelines(header)
        f.write("\n")
        f.write(playbooks)
        f.write("\n\n")
        f.writelines(new_footer)

if __name__ == "__main__":
    assemble()
