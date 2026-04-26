
import ast

file_path = "/Users/visvasis/Home/Jamvant/AscenAI/services/ai-orchestrator/app/services/seed_templates.py"

with open(file_path, 'r') as f:
    tree = ast.parse(f.read())

for node in tree.body:
    target = None
    value = None
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id == "TEMPLATES":
                target = t
                value = node.value
    elif isinstance(node, ast.AnnAssign):
        if isinstance(node.target, ast.Name) and node.target.id == "TEMPLATES":
            target = node.target
            value = node.value

    if target and value:
        if isinstance(value, ast.List):
            print(f"Number of templates: {len(value.elts)}")
            for i, t in enumerate(value.elts):
                if isinstance(t, ast.Dict):
                    key_node = next((val for j, key in enumerate(t.keys) if isinstance(key, ast.Constant) and key.value == "key" for val in [t.values[j]]), None)
                    if not key_node: # try Name if Constant fails
                         key_node = next((val for j, key in enumerate(t.keys) if isinstance(key, ast.Name) and key.id == "key" for val in [t.values[j]]), None)
                    if key_node and isinstance(key_node, ast.Constant):
                        print(f"{i+1}: {key_node.value}")
