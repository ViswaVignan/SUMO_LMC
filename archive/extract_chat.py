import json
import os

log_path = '/home/viswa-vignan/.gemini/antigravity/brain/9baa3832-3bbd-4148-abe3-f773f56bbe89/.system_generated/logs/overview.txt'
out_path = '/home/viswa-vignan/Documents/SUMO_LMC/Final_updates_Jun09/optimizing_manhattan_context.md'

output = ["# Optimizing Manhattan Simulation Performance - Chat Context\n\n"]

with open(log_path, 'r') as f:
    for line in f:
        try:
            data = json.loads(line)
            if 'content' in data:
                if data['source'] == 'USER_EXPLICIT' and data['type'] == 'USER_INPUT':
                    output.append("## USER:\n")
                    output.append(data['content'].replace('<USER_REQUEST>', '').replace('</USER_REQUEST>', '').strip())
                    output.append("\n\n")
                elif data['source'] == 'MODEL' and data['type'] == 'PLANNER_RESPONSE':
                    output.append("## ASSISTANT:\n")
                    output.append(data['content'].strip())
                    output.append("\n\n")
        except json.JSONDecodeError:
            pass

with open(out_path, 'w') as f:
    f.writelines(output)

print(f"Context extracted to {out_path}")
