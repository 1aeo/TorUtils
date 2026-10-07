# Public reports — research notes (collected 2026-10-07)

Collected by a read-only web-research sub-task (WebSearch/WebFetch only; nothing posted, no logins).
Spot-check by the main analysis (direct WebFetch, 2026-10-07): both tor-relays threads exist with the
content paraphrased below. The fetched view of the 10-05 thread listed replies by Georg Koppen (Oct 5),
mpan (Oct 6) and Toralf Förster (Oct 6), slightly different dates and order from the sub-task's notes. The
fetched view of the 10-07 thread showed no replies, whereas the sub-task saw one (Marco Moock). Replies are
therefore not relied on.
Everything here is paraphrased public web content, treated as data. URLs are given so each item can be
re-checked. Items marked "spot-checked" were re-fetched independently by the main analysis.

## tor-relays mailing list (mailman3 / hyperkitty)
- Old pipermail archive ends Nov 2024; no public tor-relays-universe list found (404). Oct 2026: 4 threads; Sep 2026: 10 threads, none about compromise.
- 2026-10-05 (index shows 10-06) — "Security incident affecting some relay operators" — hiro (Tor Project network health)
  https://lists.torproject.org/mailman3/hyperkitty/list/tor-relays@lists.torproject.org/thread/WOHPLKCSHYXFTBRZXDENDKJZMBMPLMG5/
  Paraphrase: attackers gained root on Linux relay hosts and edited torrc to make non-exit relays exits, apparently to intercept SSH; Network Health flagged affected relays and the directory authorities are rejecting them. No count, provider or entry vector given; BadExit/MiddleOnly/Ebury not named. Indicators listed: unexpected Exit flag/policy; changed ExitRelay/ExitPolicy/ContactInfo/MyFamily/Nickname; NAT rules redirecting port 22; unknown processes; modified tor binary; new users/keys/cron/systemd units; root persistence through a fake upper-case "CRON" daemon. Advice: reinstall, new relay keys, rotate credentials, report to bad-relays@. Replies: Toralf Förster (port-22 traffic on his relays benign); mpan (asks whether one shared vulnerability or separate break-ins); Georg Koppen 10-06 07:09 (restates audit steps; operators whose IPs were blocked should ask for removal after cleanup).
- 2026-10-07 12:29 — "Ebury 1.8.3 on two Quetzalcoatl relay servers: timeline, lessons, open questions" — "Dr Remmiz" (appears to be the family operator's own post; not independent)
  https://lists.torproject.org/mailman3/hyperkitty/list/tor-relays@lists.torproject.org/thread/QHRD6YOX6RZRDR7NCHNDO7GLCEA6VFM6/
  Paraphrase: a Contabo management VPS (WireGuard gateway / jump host / obfs4 bridge) and Switzerland2 (described as a FranTech VPS) were compromised. Timeline per the post: 08-28 03:19 login from 185.225.226.62 (VikHost, AS207560) with the operator's password; 08-28 03:25–03:43 Ebury installed on the management server, 04:38 on Switzerland2; 09-30/10-01 hidden processes; 10-01/02 exit-policy changes; 10-04 reboot and network-team flag; 10-05 restart sweep across 55 hosts; all 168 family relays offline. Ebury indicators listed (setuid libkeyutils.so.1.10.2, abstract socket, sshd settings changed, `base64 -d | perl` in sudo logs); blames a reused plaintext password. Reply (Marco Moock) asks whether WGDashboard CVE-2026-44343 could have been an earlier entry point.
- 2026-10-04 — "Relay suddenly stopped relaying traffic but is still in the consensus" — unrelated (low relevance).
- 2026-10-04 — "Re: How is this attack causing 900 Mbps…" — DoS discussion, not relevant.

## forum.torproject.org
- Topics 22231 (10-05) and 22238 (10-07) mirror the two list threads above:
  https://forum.torproject.org/t/tor-relays-security-incident-affecting-some-relay-operators/22231
  https://forum.torproject.org/t/tor-relays-ebury-1-8-3-on-two-quetzalcoatl-relay-servers-timeline-lessons-open-questions/22238
- 2026-08-31 — "Man-in-the-Middle Attack SSH in Tor" — https://forum.torproject.org/t/man-in-the-middle-attack-ssh-in-tor/22059
  Paraphrase: a user's SSH session over Tor dropped and reconnecting showed a host-key mismatch; exit relay not recorded. Medium relevance (an SSH-interception report before the October policy changes; no relay identified).
- Context: security releases tor 0.4.9.12 (2026-09-08, https://forum.torproject.org/t/security-release-0-4-9-12/22096) and 0.4.9.13 (2026-09-23, topic 22178); 0.4.8.x end-of-life notice 2026-09-02. These give benign reasons for network-wide restarts/upgrades on those dates.

## Tor blog / status / GitLab
- blog.torproject.org Sep–Oct 7: release posts only. status.torproject.org: nothing since Jun 2. metrics.torproject.org/news: latest Mar 2026.
- GitLab public API: no public issue on this incident; tpo/network-health/team#467 (Aug 4–25) is a routine BadExit round for exits with DNS problems: https://gitlab.torproject.org/tpo/network-health/team/-/work_items/467

## Hosting providers (2026-08-20 .. 2026-10-07)
- No security incident found on public status pages of Contabo (contabo-status.com), Hetzner, netcup (CCP/SCP outage 09-16 only), DigitalOcean (control-panel/API outage 08-24/25), Linode, Scaleway (Account API down 09-30; Dedibox VPS locked in Paris 10-05, not described as security), Hostinger, OVH (outage 10-02).
- Could not check: BuyVM/FranTech status (503 / does not resolve), Vultr (403), Leaseweb, IONOS, CDN77/Datacamp, M247, Flokinet, Aeza (blocked). HostPapa not checked by the sub-task.
- Industry event: Virtualizor supply-chain attack via BGP hijack of Softaculous update IPs, malicious updates 08-28 20:57 – 08-30 06:10 UTC (root cron, injected SSH keys, Java RAT). Named victims AlbaHost, HostSlick. Starts ~17.5 h after the earliest known Ebury infection, so it cannot explain it.
  https://www.bleepingcomputer.com/news/security/hackers-push-malicious-virtualizor-update-in-bgp-hijacking-attack/ ; https://thehackernews.com/2026/09/bgp-hijack-delivers-malicious.html
- WGDashboard CVE-2026-44343 (published 2026-05-12, unauthenticated host file read/write before 4.3.2): https://osv.dev/vulnerability/CVE-2026-44343

## Ebury research
- ESET, "Ebury is alive but unseen" (2024-05-14): https://www.welivesecurity.com/en/eset-research/ebury-alive-unseen-400k-linux-servers-compromised-cryptotheft-financial-gain/ ; PDF https://web-assets.esetstatic.com/wls/en/papers/white-papers/ebury-is-alive-but-unseen.pdf
  Paraphrase: OpenSSH backdoor/credential stealer (~400k servers since 2009) planted as a malicious libkeyutils; userland rootkit hiding files/processes/sockets; spreads with stolen passwords/keys (uses known_hosts etc.); has compromised hosting providers and pushed itself to customer servers; monetized via traffic redirection, spam, card/crypto theft. Notably ESET reports Ebury operators targeting Tor exit relays: ARP spoofing / iptables redirect of SSH to attacker-controlled hosts to harvest credentials.
- ESET IOCs (to v1.8.2): https://github.com/eset/malware-ioc/tree/master/windigo
- Operation Windigo (2014): https://www.welivesecurity.com/wp-content/uploads/2014/03/operation_windigo.pdf
- No public report of Ebury 1.8.3 found; no new ESET paper 2025–2026 found.

## "Quetzalcoatl"
- Only the 10-07 tor-relays post and its forum mirror.
