#!/bin/bash
# Migration script: End experiment and move ALL relays to production allocators
# 90% mimalloc 2.1.2 (128 relays), 10% jemalloc 5.3.0 (14 relays)
#
# Total relays: 142
#
# Run with: sudo ./migrate-to-production.sh

set -e

echo "=== Tor Relay Memory Allocator Migration ==="
echo "Target: 128 relays (90%) → mimalloc 2.1.2"
echo "        14 relays (10%) → jemalloc 5.3.0"
echo "Total:  142 relays"
echo ""

# 14 relays → jemalloc 5.3.0 (10%)
JEMALLOC_RELAYS=(
  22gz
  24kgoldn
  42dugg
  armanicaesar
  arsonaldarebel
  autumntwinuzis
  ayeverb
  babyfaceray
  babysmoove
  bbno
  bfbdapackman
  biggk
  bigpokeyhouston
  bigtuckdfw
)

# 128 relays → mimalloc 2.1.2 (90%)
MIMALLOC_RELAYS=(
  bigwalkdog
  blovee
  bluefacebaby
  boldyjames
  bonethugs
  calicoe
  caseyveggies
  cashkidd
  charlieclips
  chiefkeef
  chiiild
  cjwhoopty
  cocash
  comethazine
  conceitedwildnout
  daveeast
  davesantan
  daylytwatts
  ddgmoonwalking
  delasoul
  destroylonely
  dicesoho
  dizaster
  dnaqueens
  domaniharris
  dougieb
  dustylocane
  estgee
  estgizzle
  famousdex
  fearlessfour
  fivioforeign
  fmbdz
  foolio
  fredobang
  goodzdaanimal
  gperico
  gunna
  htowndonkee
  ianndior
  icespice
  icewearvezzo
  illmaculate
  jaycritch
  jayworthy
  joji
  kankan
  kanyc
  kayflock
  kencarson
  kingsun
  kingvon
  lakeyah
  lildurk
  lilgotit
  lilkeed
  lilloaded
  lilnasx
  lilofatrat
  lilskies
  liltecca
  liltjay
  littlesimz
  louieray
  machhommy
  millyz
  mobbdeep
  moneyman
  morray
  mozzy
  nardowick
  nastyc
  nikobrim
  nocap
  ogboobieblack
  ogche
  ombpeezy
  otthereal
  peeweelongway
  poohshiesty
  popsmoke
  problemcompton
  publicenemy
  quandorondo
  rappername
  riodayungog
  rob49
  rodwave
  romestreetz
  rundmc
  rylorodriguez
  sexyyred
  sheffg
  shordieshordie
  skepta
  slaughterhouse
  sleepyhallow
  smokepurpp
  smoovel
  sofaygo
  spotemgottem
  stormyz
  stovegodcooks
  stunna4vegas
  sugarhillgang
  swaelee
  thelox
  theroots
  threesixmafia
  toosi
  tribecalledquest
  trillsammy
  trinidadjames
  tsusurf
  tyga
  ugk
  westsidegunn
  ybncordae
  ybnnahmir
  yeattwizzyrich
  ynjay
  ynwmelly
  youngbleed
  youngnudy
  yungbleu
  yungeenace
  yungpinch
  zmoney
)

ALL_RELAYS=("${JEMALLOC_RELAYS[@]}" "${MIMALLOC_RELAYS[@]}")

echo "Step 1: Cleaning up ALL existing experiment configurations..."
echo ""

for relay in "${ALL_RELAYS[@]}"; do
  # Remove allocator override directory if exists
  if [ -d "/etc/systemd/system/tor@${relay}.service.d" ]; then
    rm -rf "/etc/systemd/system/tor@${relay}.service.d"
  fi
  
  # Stop and remove restart timer if exists
  if systemctl is-active --quiet "tor-restart@${relay}.timer" 2>/dev/null; then
    systemctl stop "tor-restart@${relay}.timer" 2>/dev/null || true
  fi
  if [ -f "/etc/systemd/system/tor-restart@${relay}.timer" ]; then
    systemctl disable "tor-restart@${relay}.timer" 2>/dev/null || true
    rm -f "/etc/systemd/system/tor-restart@${relay}.timer"
    rm -f "/etc/systemd/system/tor-restart@${relay}.service"
  fi
  
  # Remove MaxConsensusAgeForDiffs from torrc if present
  TORRC="/var/lib/tor-instances/${relay}/torrc"
  if [ -f "$TORRC" ] && grep -q "MaxConsensusAgeForDiffs" "$TORRC" 2>/dev/null; then
    sed -i '/MaxConsensusAgeForDiffs/d' "$TORRC"
  fi
done
echo "  Cleaned up all existing overrides and timers"

echo ""
echo "Step 2: Configuring jemalloc 5.3.0 for 14 relays (10%)..."
echo ""

for relay in "${JEMALLOC_RELAYS[@]}"; do
  mkdir -p "/etc/systemd/system/tor@${relay}.service.d"
  cat > "/etc/systemd/system/tor@${relay}.service.d/allocator.conf" <<EOF
[Service]
Environment="LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so.2"
EOF
done
echo "  Configured: ${JEMALLOC_RELAYS[*]}"

echo ""
echo "Step 3: Configuring mimalloc 2.1.2 for 128 relays (90%)..."
echo ""

for relay in "${MIMALLOC_RELAYS[@]}"; do
  mkdir -p "/etc/systemd/system/tor@${relay}.service.d"
  cat > "/etc/systemd/system/tor@${relay}.service.d/allocator.conf" <<EOF
[Service]
Environment="LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libmimalloc.so.2"
EOF
done
echo "  Configured ${#MIMALLOC_RELAYS[@]} relays with mimalloc 2.1.2"

echo ""
echo "Step 4: Reloading systemd..."
systemctl daemon-reload

echo ""
echo "Step 5: Restarting all 142 relays in batches..."
echo ""

# Restart in batches of 15 to avoid overwhelming the system
batch_size=15
total=${#ALL_RELAYS[@]}
batch_num=1

for ((i=0; i<total; i+=batch_size)); do
  batch=("${ALL_RELAYS[@]:i:batch_size}")
  echo "  Batch $batch_num: Restarting ${#batch[@]} relays..."
  
  # Build the brace expansion string
  relay_list=$(IFS=,; echo "${batch[*]}")
  eval "systemctl restart tor@{${relay_list}}"
  
  batch_num=$((batch_num + 1))
  
  # Small delay between batches
  sleep 2
done

echo ""
echo "Step 6: Verifying all relays are running..."
running=$(systemctl list-units 'tor@*' --state=running --no-legend | wc -l)
failed=$(systemctl list-units 'tor@*' --state=failed --no-legend | wc -l)

echo "  Running: $running"
echo "  Failed:  $failed"

if [ "$failed" -gt 0 ]; then
  echo ""
  echo "WARNING: Some relays failed to start:"
  systemctl list-units 'tor@*' --state=failed --no-legend
fi

echo ""
echo "=== Migration Complete ==="
echo ""
echo "Summary:"
echo "  - 14 relays on jemalloc 5.3.0 (10%)"
echo "  - 128 relays on mimalloc 2.1.2 (90%)"
echo "  - Total: 142 relays"
echo ""
echo "Verify allocators are loaded:"
echo "  # Check jemalloc relay"
echo "  pid=\$(systemctl show tor@22gz --property=MainPID --value)"
echo "  sudo cat /proc/\$pid/maps | grep jemalloc"
echo ""
echo "  # Check mimalloc relay"
echo "  pid=\$(systemctl show tor@zmoney --property=MainPID --value)"
echo "  sudo cat /proc/\$pid/maps | grep mimalloc"
