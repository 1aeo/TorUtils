| Cell | Unpatched | Patched | Regression? |
|---|---|---|---|
| minimal | green | green | no |
| hardened | FAIL: unittest_part7.sh; failed cases: chmod_filename, chown_filename, crypto_equix, is_active, rename_filename | FAIL: unittest_part7.sh; failed cases: chmod_filename, chown_filename, crypto_equix, is_active, rename_filename | no |
| distcheck | green | green | no |
| disable-relay | FAIL: test_cbt_mvp.sh | green | no |
| disable-dirauth | green | green | no |
| gpl | green | green | no |
| nss | green | green | no |
| docs | green | green | no |
| tracing | green | green | no |
| integration | FAIL: bridges+ipv6-min, hs-v3-ipv6, ipv6-exit-min, single-onion-v3-ipv6-md; chutney PASS 4 (basic-min, bridges-min, hs-v3-min, single-onion-v3); FAIL 4 (bridges+ipv6-min, hs-v3-ipv6, ipv6-exit-min, single-onion-v3-ipv6-md); stem: tor failed to start (cannot bind [::]; no IPv6 in container) | FAIL: bridges+ipv6-min, hs-v3-ipv6, ipv6-exit-min, single-onion-v3-ipv6-md; chutney PASS 4 (basic-min, bridges-min, hs-v3-min, single-onion-v3); FAIL 4 (bridges+ipv6-min, hs-v3-ipv6, ipv6-exit-min, single-onion-v3-ipv6-md); stem: tor failed to start (cannot bind [::]; no IPv6 in container) | no |

Regressions (pass unpatched, fail patched): none
