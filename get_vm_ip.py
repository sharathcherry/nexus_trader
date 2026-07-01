import subprocess

cmd = [
    "az.cmd", "vm", "list-ip-addresses",
    "--resource-group", "NEXUS-TRADER-RG",
    "--name", "nexus-trader-vm",
    "--query", "[0].virtualMachine.network.publicIpAddresses[0].ipAddress",
    "-o", "tsv"
]

print("Fetching VM IP address...")
res = subprocess.run(cmd, capture_output=True, text=True)

if res.returncode != 0:
    print("STDERR:", res.stderr)
else:
    ip = res.stdout.strip()
    print("Public IP:", ip)
