## 1. The workflow stops spelling the release it binds

- [x] 1.1 Derive the trust configuration path from the pinned client version rather than naming one file, and derive the OpenAPI, conformance, and migration asset patterns from the version and schema that configuration states.
- [x] 1.2 Prove it: pointing the pin at another version changes every asset the workflow asks for, with no edit to the workflow.

## 2. A dev-pace check can compile against an unreleased version

- [x] 2.1 Compare the pinned client version with the version the trusted release names, in one step, and select the channel from that comparison alone.
- [x] 2.2 On the released path, download and verify exactly as today.
- [x] 2.3 On the unreleased path, fetch the wheel from the private index into `.dist` and verify nothing, because nothing signed it.
- [x] 2.4 Report an unreachable channel as an unavailable prerequisite naming the version and the channel, before resolution is attempted.
- [x] 2.5 Prove the selection and both paths against the real workflow file, without needing CI to run.

## 3. Say what the federation has to provide

- [x] 3.1 Record in the change what must exist outside this repository — identity pool and provider, service account and its read binding, repository variables — and what each is for.
