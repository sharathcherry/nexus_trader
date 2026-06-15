import base64
import subprocess

with open("deploy_services.sh", "rb") as f:
    script_data = f.read().replace(b'\r\n', b'\n')

b64 = base64.b64encode(script_data).decode("utf-8")

settings = f'{{"script": "{b64}"}}'

cmd = [
    "az.cmd", "vm", "extension", "set",
    "--resource-group", "NEXUS-TRADER-RG",
    "--vm-name", "nexus-trader-vm",
    "--name", "CustomScript",
    "--publisher", "Microsoft.Azure.Extensions",
    "--protected-settings", settings
]

print("Running command...")
res = subprocess.run(cmd, capture_output=True, text=True)
print("STDOUT:", res.stdout)
print("STDERR:", res.stderr)
