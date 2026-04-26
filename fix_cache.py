import os
import re

directory = '/Users/visvasis/Home/Jamvant/ascenai/frontend/web/src/app/(dashboard)/dashboard/agents'

for root, dirs, files in os.walk(directory):
    for file in files:
        if file.endswith('.tsx'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r') as f:
                content = f.read()

            # The exact string is usually: qc.invalidateQueries({ queryKey: ['agent', id] })
            # Replace it with: qc.invalidateQueries({ queryKey: ['agent', id] }); qc.invalidateQueries({ queryKey: ['agents'] })
            
            # Use regex to match different spacing forms
            pattern = re.compile(r'(qc\.invalidateQueries\(\{\s*queryKey:\s*\[\'agent\',\s*(?:id|agentId)\]\s*\}\))')
            
            def replacer(match):
                return match.group(1) + "\n      qc.invalidateQueries({ queryKey: ['agents'] })"
            
            new_content = pattern.sub(replacer, content)
            
            if new_content != content:
                with open(filepath, 'w') as f:
                    f.write(new_content)
                print(f"Fixed {filepath}")
