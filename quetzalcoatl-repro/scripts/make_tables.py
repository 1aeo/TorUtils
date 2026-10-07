#!/usr/bin/env python3
"""make_tables.py - render markdown tables (appendices) for out/FINDINGS.md and NETWORK_FINDINGS.md from CSVs.

Writes:
  out/_appendix_policy_changes.md   all family policy changes since 2026-08-01 (fingerprint, nickname, IP,
                                    old class, new class, published, reload/restart, boot time)
  out/_appendix_bursts.md           family host-event bursts (>=5 hosts, 20-min chaining) since 2026-08-20 with
                                    host order statistics, plus the full host order of the key bursts
  net/_appendix_victims.md          every victim relay with state at end of window
  net/_appendix_waves.md            wave table
"""
import csv
import os


def md(rows, hdr):
    out = ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
    for r in rows:
        out.append("| " + " | ".join(str(x).replace("|", "/") for x in r) + " |")
    return "\n".join(out)


def main():
    pc = list(csv.DictReader(open("out/repro_policy_changes.csv")))
    rows = [[r["fingerprint"], r["nickname"], r["ip"], r["old_policy_class"], r["new_policy_class"], r["published"],
             r["reload_or_restart"], r["boot_time"], "AS" + r["asn"]] for r in pc]
    with open("out/_appendix_policy_changes.md", "w") as f:
        f.write("### Appendix A. Every family exit-policy change since 2026-08-01 (descriptor level)\n\n")
        f.write("Source: net/netdb.sqlite tables policy_event + descriptor; also out/repro_policy_changes.csv. "
                "Classes from the re-implemented policy_summarize(). boot_time = published - uptime.\n\n")
        f.write(md(rows, ["fingerprint", "nickname", "IP", "old class", "new class", "published (UTC)",
                          "reload/restart", "boot time", "AS"]) + "\n")
    b = list(csv.DictReader(open("out/repro_bursts.csv")))
    rows = []
    for r in b:
        if r["chain_gap_min"] == "20" and r["start"] >= "2026-08-20":
            pairs = int(r["pairs"])
            rows.append([r["start"], r["end"], r["hosts"], r["relays"], r["event_types"],
                         "%s/%s/%s of %d" % (r["inv_str"], r["inv_num"], r["inv_nodot"], pairs),
                         "%s/%s/%s" % (r["longest_run_str"], r["longest_run_num"], r["longest_run_nodot"]),
                         r["kendall_tau_vs_earlier_runs(last 6)"][-60:]])
    with open("out/_appendix_bursts.md", "w") as f:
        f.write("### Appendix B. Family host-event bursts since 2026-08-20 (>=5 hosts, gaps <= 20 min, seconds)\n\n")
        f.write("Inversions against text / numeric / dotless sort of the IPs; a random order gives about half of the "
                "pairs. Longest ascending runs in the same three orders. Kendall tau against the family's earlier "
                "bursts with >=10 common hosts (last six shown). Source: out/repro_bursts.csv.\n\n")
        f.write(md(rows, ["start", "end", "hosts", "relays", "events", "inversions str/num/nodot",
                          "longest run str/num/nodot", "tau vs earlier runs"]) + "\n\n")
        for r in b:
            if r["chain_gap_min"] == "20" and r["start"][:16] in ("2026-10-01 15:36", "2026-10-02 09:27",
                                                                  "2026-10-04 01:10", "2026-10-05 08:56",
                                                                  "2026-09-08 23:47", "2026-09-23 23:33"):
                f.write("Host order, burst %s .. %s (%s hosts): %s\n\n" % (r["start"], r["end"], r["hosts"],
                                                                            r["host_order"]))
    v = list(csv.DictReader(open("net/victims.csv")))
    rows = [[r["fp"], r["nickname"], r["ip"], r["asn"], r["family"], r["operator"][:45],
             r["class_before_first_attacker_desc"][:16], r["first_attacker_desc"], r["first_attacker_class"],
             r["last_desc"], r["last_desc_class"], r["last_consensus_va"], r["ever_badexit"], r["ever_middleonly"]]
            for r in sorted(v, key=lambda r: (r["first_attacker_desc"], r["fp"]))]
    with open("net/_appendix_victims.md", "w") as f:
        f.write("### Appendix V. Every victim relay (377), ordered by first attacker-class descriptor\n\n")
        f.write("Source: net/victims.csv. family=1: Quetzalcoatl family. last_consensus_va is the relay's last "
                "consensus appearance; the last consensus scanned is 2026-10-07 02:00:00.\n\n")
        f.write(md(rows, ["fingerprint", "nickname", "IP (last)", "AS", "family", "operator (contact, truncated)",
                          "class before", "first attacker descriptor", "class", "last descriptor", "last class",
                          "last consensus", "BadExit ever", "MiddleOnly ever"]) + "\n")
    w = list(csv.DictReader(open("net/waves_15min.csv")))
    rows = [[r["wave"], r["start"], r["end"], r["events"], r["relays"], r["hosts"], r["family_events"],
             r["directions"], r["kinds"], r["n_operators"], r["ases"][:120]] for r in w]
    with open("net/_appendix_waves.md", "w") as f:
        f.write(md(rows, ["wave", "start", "end", "events", "relays", "hosts", "family events", "directions",
                          "reload/restart", "operators", "ASes"]) + "\n")


if __name__ == "__main__":
    main()
