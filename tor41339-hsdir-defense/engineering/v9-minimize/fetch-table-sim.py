"""How many keys a minute can hold in 0019's table before some find no slot:
4096 slots, and a key may land at most 16 slots after its own (linear
probing). Keys are random, as their siphash is. Run: python3 -I this file."""
import random
SLOTS, PROBES = 4096, 16
for n in (1000, 2000, 2500, 2800, 3000, 3200, 3500, 4096):
    fails = []
    for trial in range(20):
        t = [None] * SLOTS
        f = 0
        for k in range(n):
            h = random.getrandbits(64)
            for i in range(PROBES):
                s = (h + i) % SLOTS
                if t[s] is None:
                    t[s] = h
                    break
            else:
                f += 1
        fails.append(f / n)
    print(n, "keys: %.2f%% of keys find no slot" % (100 * sum(fails) / len(fails)))
