import xml.etree.ElementTree as ET

tree = ET.parse('simulation_trace_20260717_213918.xml')
root = tree.getroot()

stats = {"parked": 0, "vanished": 0, "dropping_off": 0, "picking_up": 0, "idle": 0}

for step in root.findall('step'):
    for v_el in step.findall('vehicles'):
        for veh in v_el.findall('vehicle'):
            status = veh.get('status')
            stats[status] = stats.get(status, 0) + 1

print(stats)
