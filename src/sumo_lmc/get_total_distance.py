import xml.etree.ElementTree as ET

tree = ET.parse('simulation_trace_20260717_213918.xml')
root = tree.getroot()

total_active_steps = 0
for step in root.findall('step'):
    for v_el in step.findall('vehicles'):
        for veh in v_el.findall('vehicle'):
            status = veh.get('status')
            if status not in ('parked', 'vanished'):
                total_active_steps += 1

print(f"Total Active Steps: {total_active_steps}")
print(f"Total Shared Fleet Travel Distance: {total_active_steps * 30 * 8.33:,.2f} meters")
