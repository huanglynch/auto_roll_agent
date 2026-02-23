#!/bin/bash
set -e
echo "=== TSLA Auto Roll 一键部署 (2026版) ==="

apt update && apt upgrade -y
apt install -y curl wget unzip openjdk-17-jre-headless screen jq python3-pip

useradd -m -s /bin/bash ibkr || true
echo "ibkr ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

su - ibkr << 'EOF'
cd ~
wget -q https://download2.interactivebrokers.com/installers/ibgateway/latest-standalone/ibgateway-latest-standalone-linux-x64.sh
chmod +x ibgateway-latest-standalone-linux-x64.sh
echo "n" | ./ibgateway-latest-standalone-linux-x64.sh -c

wget -q https://github.com/IbcAlpha/IBC/releases/latest/download/IBC-Linux-x64.zip
unzip -o IBC-Linux-x64.zip -d ~/IBC
chmod +x ~/IBC/scripts/*.sh
EOF

cp config.json /home/ibkr/
cp tsla_auto_roll_ibkr.py /home/ibkr/
chown -R ibkr:ibkr /home/ibkr/
chmod +x /home/ibkr/tsla_auto_roll_ibkr.py

cat > /etc/systemd/system/tsla-roll.service << EOF
[Unit]
Description=TSLA Auto Roll
After=network.target

[Service]
User=ibkr
WorkingDirectory=/home/ibkr
ExecStart=/usr/bin/python3 /home/ibkr/tsla_auto_roll_ibkr.py
Restart=always
RestartSec=10
StandardOutput=append:/home/ibkr/roll.log
StandardError=append:/home/ibkr/roll.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now tsla-roll.service

echo "部署完成！"
echo "日志: tail -f /home/ibkr/roll.log"
echo "状态: systemctl status tsla-roll"
