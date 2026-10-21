import subprocess
import json

command = [
    "powershell",
    "-NoProfile",
    "-Command",
    "Get-CimInstance Win32_PhysicalMemory | "
    "Select-Object DeviceLocator, Manufacturer, PartNumber, "
    "Capacity, Speed, ConfiguredClockSpeed, MemoryType, "
    "SMBIOSMemoryType, SerialNumber, FormFactor | "
    "ConvertTo-Json -Depth 3"
]

result = subprocess.run(
    command,
    capture_output=True,
    text=True,
    check=True
)

modules = json.loads(result.stdout)

if isinstance(modules, dict):
    modules = [modules]

for i, ram in enumerate(modules, 1):
    print(f"\n--- RAM stick {i} ---")
    print(f"Slot: {ram.get('DeviceLocator')}")
    print(f"Manufacturer: {ram.get('Manufacturer')}")
    print(f"Part number: {ram.get('PartNumber')}")
    print(f"Capacity: {int(ram.get('Capacity') or 0) / (1024**3):.0f} GB")
    print(f"Rated speed: {ram.get('Speed')} MT/s")
    print(f"Configured speed: {ram.get('ConfiguredClockSpeed')} MT/s")
    print(f"Memory type code: {ram.get('SMBIOSMemoryType')}")
    print(f"Serial number: {ram.get('SerialNumber')}")
    print(f"Form factor code: {ram.get('FormFactor')}")