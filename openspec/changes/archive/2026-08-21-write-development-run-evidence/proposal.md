## Why

A development run of the hosted scenario body executes its scenario and then
throws the result away. `write_evidence` refuses every such run with
`consumer, hosted release, and run identities must be exact`, so the only
output an operator gets is the process exit code. Whatever the run found —
which stage it reached, what refused it, whether funding succeeded — is
discarded at the last step.

The cause is one stale assumption, still written in the code as a comment:
*"The producer is a released one in every mode."* That was true until
`build-hosted-producer-locally` made a locally built producer a first-class
input. The marketplace half of the same validator was taught the difference —
it checks the released coordinates only when the mode is attested, and
otherwise requires the image the run actually named. The producer half was
not, so it still demands a source commit, a workflow run id, a workflow ref,
and three release digests that a locally built producer has none of and
correctly records as `local`.

This contradicts a requirement already in the specs: a run against a locally
built authority "runs its scenario end to end against that image, and the run
is recorded as a development run". A run that cannot record itself has not run
end to end.

## What Changes

- Producer identity evidence is validated against the mode the run recorded,
  the way consumer identity evidence already is. A locally built producer's
  released coordinates must each be exactly the self-describing `local`
  marker; a released producer's must each be exact, as today.
- Because release mode is a property of the run and either half may be the
  local one, each half is judged on its own coordinates, and a half that is
  partly released and partly local is refused — the same rule the binding
  gate applies when it admits the run in the first place.
- A locally built producer records what it does have: the image the run named
  and the manifest digest the authority reported. Evidence that records `local`
  six times and nothing else names no producer at all.
- **BREAKING** for readers of the evidence document: producer identity gains
  two fields. Existing attested evidence keeps every field it has today.

## Capabilities

### Modified Capabilities

- `deployment-state`: the requirement that a development run needs no release
  infrastructure already covers running end to end. State that recording the
  run is part of that, and what a locally built half records in place of
  coordinates it does not have.

## Impact

- `e2e-tests/src/hosted_real_stripe/evidence.py` — identity validation and the
  producer identity shape.
- `e2e-tests/src/hosted_real_stripe/driver.py` — populates the two new fields.
- No change to what is admitted: the binding gate already decides released
  versus local, and this only stops the evidence writer from contradicting it.
