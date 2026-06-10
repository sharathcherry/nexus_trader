#!/bin/bash
echo "Finding repo..."
REPO_DIR=$(find /home -type d -name "nexus_trader" 2>/dev/null | head -n 1)

if [ -n "$REPO_DIR" ]; then
    echo "Found repo at $REPO_DIR"
    
    # Run all git and pip commands as the azureuser who owns the folder
    su - azureuser -c "cd $REPO_DIR && git config --global --add safe.directory $REPO_DIR && rm -f logs/decisions/*.log && git pull origin main && pip3 install -r requirements.txt"
    
    echo "Restarting systemd service..."
    systemctl restart nexus_trader
    
    echo "Update complete!"
else
    echo "Could not find nexus_trader directory in /home."
fi
