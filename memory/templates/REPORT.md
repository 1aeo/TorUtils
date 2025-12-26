# [Experiment Title]

## Executive Summary

**Problem:** [One-line problem statement]  
**Hypothesis:** [What we expected to find]  
**Result:** [What we actually found]  
**Recommendation:** [Action to take based on findings]

## Experiment Setup

| Parameter | Value |
|-----------|-------|
| Server | [hostname] |
| Period | [start] to [end] |
| Tor Version | [version] |
| Allocator | [glibc/jemalloc/tcmalloc] |
| Relay Count | [N] |

### Groups

| Group | Configuration | Relays | Description |
|-------|---------------|--------|-------------|
| A | [config details] | [N] | [purpose] |
| B | [config details] | [N] | [purpose] |

## Results

### Key Metrics

| Group | Start RSS | End RSS | Change | Status |
|-------|-----------|---------|--------|--------|
| A | X.XX GB | Y.YY GB | -Z% | [STABLE/FRAGMENTED] |
| B | X.XX GB | Y.YY GB | +Z% | [STABLE/FRAGMENTED] |

### Charts

![Memory Over Time](charts/memory_over_time.png)

![Group Comparison](charts/group_comparison.png)

![Per-Relay Distribution](charts/relay_distribution.png)

## Analysis

### What Worked

- [Finding 1: Description of positive result]
- [Finding 2: Description of positive result]

### What Didn't Work

- [Finding 1: Description of negative result]
- [Finding 2: Description of negative result]

### Unexpected Observations

- [Observation 1: Something surprising discovered]
- [Observation 2: Something surprising discovered]

## Root Cause

[Detailed explanation of why the results occurred. Include technical details about the underlying mechanisms.]

## Recommendations

1. **[Recommendation 1]**: [Detailed action item]
2. **[Recommendation 2]**: [Detailed action item]
3. **[Recommendation 3]**: [Detailed action item]

## Next Steps

- [ ] [Follow-up experiment or action]
- [ ] [Configuration change to implement]
- [ ] [Documentation to update]
- [ ] [Report to submit to Tor Project]

## Data Reference

- **Experiment directory**: `[path]`
- **Measurements**: `measurements.csv` ([N] data points, [N] relays)
- **Relay config**: `relay_config.csv`
- **Raw data period**: [start] to [end]

## References

1. [Tor Support: Relay Memory](https://support.torproject.org/relay-operators/relay-memory/)
2. [Tor Manual](https://2019.www.torproject.org/docs/tor-manual.html.en)
3. [Additional reference]

---

*Experiment conducted: [start] to [end]*  
*Report generated: [date]*  
*Author: [name/team]*

