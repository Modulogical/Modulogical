
import platform
import psutil
import subprocess

print("=== CPU INFORMATION ===")
print(f"OS: {platform.system()} {platform.release()}")
print(f"Logical processors: {psutil.cpu_count(logical=True)}")
print(f"Physical cores: {psutil.cpu_count(logical=False)}")
print(f"Current frequency: {psutil.cpu_freq().current:.0f} MHz")

try:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "(Get-CimInstance Win32_Processor | "
            "Select-Object -First 1 -ExpandProperty Name)"
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=True
    )

    print(f"Exact CPU model: {result.stdout.strip()}")

except Exception as e:
    print(f"Could not identify exact CPU: {e}")
