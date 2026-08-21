## 1. The reason lasts as long as the park

- [x] 1.1 Reproduce: park a collection, then reconcile status once with an
      adapter that returns the state it derives rather than the state it was
      handed, and observe the reason gone while the park remains.
- [x] 1.2 While any operation state is `manual_required`, a write that names no
      reason preserves the one already recorded.
- [x] 1.3 A write that names its own reason replaces the recorded one.
- [x] 1.4 Once no operation state is `manual_required`, nothing is carried.
- [x] 1.5 Evidence: the reproduction now passes; a status write naming its own
      reason replaces the carried one; an obligation that was never parked
      still carries nothing. Suites: settlement-runtime 82, hosted-settlement
      183, VM storefront 1101, API-credits 77, bare metal 124.
