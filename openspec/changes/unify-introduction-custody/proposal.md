# Unify introduction custody

## Why

The contact-exchange mechanism introduces a buyer and a seller after an accepted deal, and
`kit/contact-exchange` holds the contacts it reveals. Goal 9's RFQs introduce a buyer and a
respondent after both consent, and the registry must hold those contacts too, since buyers
run no service of their own. The earlier implementation of RFQs built a second custody stack
in the registry with different protection, different retention rules and different operator
procedures. Two mechanisms for one job is duplication to remove before RFQs land.

Each had strengths the other lacked. Contact exchange redacts one-way, enforced in the
database, discloses its retention window before commitment, and gives operators a sweep they
can preview and step. The RFQ stack encrypted contacts at rest, let either participant end
access early, swept before admitting traffic after downtime, and redacted a restored backup.
This change builds one custody layer with both sets.

## What Changes

- **One introduction custody layer** serves contact-exchange settlement in the storefronts and
  RFQ introductions in the registry. It knows nothing of settlement or RFQs (design D1).
- **Contacts are encrypted at rest everywhere**, storefronts included, with the key held
  outside the database and rotatable (D2).
- **Redaction is one-way and enforced by the database**, and a read after redaction answers a
  stable deleted outcome stating when (D3).
- **Retention is one running policy** over everything held, disclosed before commitment and at
  reveal as current policy rather than a promise. `indefinite` is a policy the layer allows and
  a host may refuse (D4).
- **Either participant may end access** for both (D5).
- **Operators preview and step the sweep**, which also runs before traffic is admitted after
  downtime and reports overdue payloads (D6).
- **A restored backup can be redacted** before reads reopen (D7).
- **Contact payloads are validated once**, by one bounded validator (D8).
- **Each side's delivery to its own sinks** stays as `introduction-delivery` defines it (D9).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `contact-exchange-settlement`: custody moves beneath it into the shared layer, gaining
  encryption, early end, startup sweep and restore redaction.
- `introduction-delivery`: unchanged in behavior; it reads from the shared layer.

## Dependencies and Related Changes

- `add-buyer-compute-rfqs` depends on it, and adds the stage before selection on top of it.

## Permanent documentation impact

- [x] The repository's architecture document
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: one custody layer to `contact-exchange-settlement` and `docs/development/ARCHITECTURE.md`.
- D2: encryption at rest to `contact-exchange-settlement`, its configuration,
  `docs/operator-handbook.md` and `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- D3: one-way redaction to `contact-exchange-settlement`.
- D4: retention as one running policy to `contact-exchange-settlement` and its configuration.
- D5: early end by a participant to `contact-exchange-settlement`.
- D6: the sweep to `contact-exchange-settlement` and `docs/operator-handbook.md`.
- D7: restore redaction to `contact-exchange-settlement` and `docs/operator-handbook.md`.
- D8: one payload validator to `contact-exchange-settlement`.
- D9: delivery unchanged to `introduction-delivery`.
