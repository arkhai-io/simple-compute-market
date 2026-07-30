# Capacity host-operator instruction

The host-operator agent owns the admitted one-GPU VM host boundary for one
capacity stage. It must remain distinct from the controller and independent
observer.

Before release, the agent must:

1. inspect this exact instruction at the pinned SCM commit;
2. verify the private topology authority admits exactly one independently
   assignable whole GPU;
3. verify KVM, whole-device passthrough, and Ansible readiness;
4. capture the reversible baseline and the expected append-only/accounting
   delta policy through owner-only native evidence;
5. prepare host-side observation and teardown plans; and
6. expose only the contract's typed privacy-preserving bindings and public
   digests.

The agent remains alive from admission through cleanup. It observes the
host-side lifecycle, tears down every run-owned VM and reversible resource,
checks for zero active residue or locks, reconciles all expected immutable and
accounting deltas, and records final baseline equivalence.

Never copy a project, host, interface, endpoint, PCI address, GPU identifier,
credential, private evidence path, or native evidence value into a portable
SCM artifact.
