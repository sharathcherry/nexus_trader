cat << 'EOF' > /etc/systemd/system/nexus-trader.service
[Unit]
Description=Nexus Trader Bot
After=network.target

[Service]
Type=simple
User=azureuser
WorkingDirectory=/home/azureuser/nexus_trader
ExecStart=/home/azureuser/nexus_trader/venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

cat << 'EOF' > /etc/systemd/system/nexus-dashboard.service
[Unit]
Description=Nexus Trader Dashboard
After=network.target

[Service]
Type=simple
User=azureuser
WorkingDirectory=/home/azureuser/nexus_trader
ExecStart=/home/azureuser/nexus_trader/venv/bin/python server.py 8080
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable nexus-trader.service
systemctl enable nexus-dashboard.service
systemctl start nexus-trader.service
systemctl start nexus-dashboard.service
systemctl status nexus-trader.service --no-pager
systemctl status nexus-dashboard.service --no-pager
