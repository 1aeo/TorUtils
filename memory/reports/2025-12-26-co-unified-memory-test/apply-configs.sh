#!/bin/bash
#
# Apply experiment configurations to relays
# Run with: sudo ./apply-configs.sh
#

set -euo pipefail

echo "=== Applying Unified Memory Experiment Configurations ==="
echo ""

# Group A (jemalloc) - 10 relays
GROUP_A="22gz 24kgoldn 42dugg armanicaesar arsonaldarebel autumntwinuzis ayeverb babyfaceray babysmoove bbno"

# Group B (mimalloc) - 10 relays
GROUP_B="bfbdapackman biggk bigpokeyhouston bigtuckdfw bigwalkdog blovee bluefacebaby boldyjames bonethugs calicoe"

# Group C (tcmalloc) - 10 relays
GROUP_C="caseyveggies cashkidd charlieclips chiefkeef chiiild cjwhoopty cocash comethazine conceitedwildnout daveeast"

# Group D (consensus-4h) - 10 relays
GROUP_D="davesantan daylytwatts ddgmoonwalking delasoul destroylonely dicesoho dizaster dnaqueens domaniharris dougieb"

# Group E (consensus-8h) - 10 relays
GROUP_E="dustylocane estgee estgizzle famousdex fearlessfour fivioforeign fmbdz foolio fredobang goodzdaanimal"

# Group F (restart-24h) - 10 relays
GROUP_F="gperico gunna htowndonkee ianndior icespice icewearvezzo illmaculate jaycritch jayworthy joji"

# Group G (restart-48h) - 10 relays
GROUP_G="kankan kanyc kayflock kencarson kingsun kingvon lakeyah lildurk lilgotit lilkeed"

# Group H (restart-72h) - 10 relays
GROUP_H="lilloaded lilnasx lilofatrat lilskies liltecca liltjay littlesimz louieray machhommy millyz"

# Group Z (control) - 10 relays - no changes needed
GROUP_Z="mobbdeep moneyman morray mozzy nardowick nastyc nikobrim nocap ogboobieblack ogche"

echo "--- Group A: jemalloc allocator (10 relays) ---"
for relay in $GROUP_A; do
  mkdir -p /etc/systemd/system/tor@${relay}.service.d/
  cat > /etc/systemd/system/tor@${relay}.service.d/allocator.conf <<EOF
[Service]
Environment="LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so.2"
EOF
  echo "  Created override for $relay"
done

echo ""
echo "--- Group B: mimalloc allocator (10 relays) ---"
for relay in $GROUP_B; do
  mkdir -p /etc/systemd/system/tor@${relay}.service.d/
  cat > /etc/systemd/system/tor@${relay}.service.d/allocator.conf <<EOF
[Service]
Environment="LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libmimalloc.so.2"
EOF
  echo "  Created override for $relay"
done

echo ""
echo "--- Group C: tcmalloc allocator (10 relays) ---"
for relay in $GROUP_C; do
  mkdir -p /etc/systemd/system/tor@${relay}.service.d/
  cat > /etc/systemd/system/tor@${relay}.service.d/allocator.conf <<EOF
[Service]
Environment="LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libtcmalloc.so.4"
EOF
  echo "  Created override for $relay"
done

echo ""
echo "--- Group D: MaxConsensusAgeForDiffs 4h (10 relays) ---"
for relay in $GROUP_D; do
  # Check if already configured
  if ! grep -q "MaxConsensusAgeForDiffs" /etc/tor/instances/${relay}/torrc 2>/dev/null; then
    echo "MaxConsensusAgeForDiffs 14400" >> /etc/tor/instances/${relay}/torrc
    echo "  Added MaxConsensusAgeForDiffs 14400 to $relay"
  else
    echo "  $relay already has MaxConsensusAgeForDiffs configured"
  fi
done

echo ""
echo "--- Group E: MaxConsensusAgeForDiffs 8h (10 relays) ---"
for relay in $GROUP_E; do
  # Check if already configured
  if ! grep -q "MaxConsensusAgeForDiffs" /etc/tor/instances/${relay}/torrc 2>/dev/null; then
    echo "MaxConsensusAgeForDiffs 28800" >> /etc/tor/instances/${relay}/torrc
    echo "  Added MaxConsensusAgeForDiffs 28800 to $relay"
  else
    echo "  $relay already has MaxConsensusAgeForDiffs configured"
  fi
done

echo ""
echo "--- Creating restart service template ---"
cat > /etc/systemd/system/tor-restart@.service <<EOF
[Unit]
Description=Restart Tor relay %i

[Service]
Type=oneshot
ExecStart=/bin/systemctl restart tor@%i
EOF
echo "  Created /etc/systemd/system/tor-restart@.service"

echo ""
echo "--- Group F: 24-hour restart timers (10 relays) ---"
for relay in $GROUP_F; do
  cat > /etc/systemd/system/tor-restart-${relay}.timer <<EOF
[Unit]
Description=Restart tor@${relay} every 24 hours

[Timer]
OnBootSec=24h
OnUnitActiveSec=24h
RandomizedDelaySec=300
Unit=tor-restart@${relay}.service

[Install]
WantedBy=timers.target
EOF
  echo "  Created timer for $relay (24h)"
done

echo ""
echo "--- Group G: 48-hour restart timers (10 relays) ---"
for relay in $GROUP_G; do
  cat > /etc/systemd/system/tor-restart-${relay}.timer <<EOF
[Unit]
Description=Restart tor@${relay} every 48 hours

[Timer]
OnBootSec=48h
OnUnitActiveSec=48h
RandomizedDelaySec=300
Unit=tor-restart@${relay}.service

[Install]
WantedBy=timers.target
EOF
  echo "  Created timer for $relay (48h)"
done

echo ""
echo "--- Group H: 72-hour restart timers (10 relays) ---"
for relay in $GROUP_H; do
  cat > /etc/systemd/system/tor-restart-${relay}.timer <<EOF
[Unit]
Description=Restart tor@${relay} every 72 hours

[Timer]
OnBootSec=72h
OnUnitActiveSec=72h
RandomizedDelaySec=300
Unit=tor-restart@${relay}.service

[Install]
WantedBy=timers.target
EOF
  echo "  Created timer for $relay (72h)"
done

echo ""
echo "--- Group Z: Control group (10 relays) ---"
echo "  No changes needed for control group"

echo ""
echo "=== Reloading systemd ==="
systemctl daemon-reload

echo ""
echo "=== Enabling restart timers ==="
for relay in $GROUP_F $GROUP_G $GROUP_H; do
  systemctl enable tor-restart-${relay}.timer
  systemctl start tor-restart-${relay}.timer
  echo "  Enabled timer for $relay"
done

echo ""
echo "=== Restarting allocator groups (A/B/C) ==="
for relay in $GROUP_A $GROUP_B $GROUP_C; do
  systemctl restart tor@${relay}
  echo "  Restarted $relay"
done

echo ""
echo "=== Restarting consensus diff groups (D/E) ==="
for relay in $GROUP_D $GROUP_E; do
  systemctl restart tor@${relay}
  echo "  Restarted $relay"
done

echo ""
echo "=== Configuration complete! ==="
echo ""
echo "Summary:"
echo "  - Group A (jemalloc): 10 relays with LD_PRELOAD"
echo "  - Group B (mimalloc): 10 relays with LD_PRELOAD"
echo "  - Group C (tcmalloc): 10 relays with LD_PRELOAD"
echo "  - Group D (consensus-4h): 10 relays with MaxConsensusAgeForDiffs 14400"
echo "  - Group E (consensus-8h): 10 relays with MaxConsensusAgeForDiffs 28800"
echo "  - Group F (restart-24h): 10 relays with 24h restart timer"
echo "  - Group G (restart-48h): 10 relays with 48h restart timer"
echo "  - Group H (restart-72h): 10 relays with 72h restart timer"
echo "  - Group Z (control): 10 relays unchanged"
echo ""
echo "Total: 90 relays configured"
echo ""
echo "Next: Set up cron for data collection (every 6 hours)"

