## ADDED Requirements

### Requirement: The site's ending and release transitions record their events

Every transition that records a `lease_ended` event MUST also record a `site.lease_ended` event, keyed on the reservation and the transition's key, carrying that payload as its `details`, in the same transaction, through the event recorder its composition injects. A release that frees a reservation's capacity MUST record a `site.capacity_released` event, keyed on the reservation, with whether it was forced, whether the reservation was `release_failed` before it, and whether the lease lifecycle made it through the site authority port rather than a caller of the site's release route, in the same transaction.

#### Scenario: A lease ends

- **WHEN** a lease's ending transition commits
- **THEN** its immutable `lease_ended` record and one `site.lease_ended` event carrying the same payload exist, and a repeated transition records neither again

#### Scenario: An operator force-releases a lease left release_failed

- **WHEN** an operator force-releases a reservation that was `release_failed`
- **THEN** the release records one `site.capacity_released` event whose `forced` and `after_release_failure` attributes are true

#### Scenario: A caller of the site's release route releases a reservation

- **WHEN** a reservation is released through the site's release route rather than by the lease lifecycle
- **THEN** its `site.capacity_released` event's `lease_lifecycle` attribute is false, as it is true for a release the lease lifecycle makes

#### Scenario: A release is refused by its guard

- **WHEN** the release guard refuses to free a reservation's capacity
- **THEN** no `site.capacity_released` event is recorded

### Requirement: A failing transition records a caller's prepared event

The site's release-failure transition MUST accept an optional prepared event from its caller and record it in the transition's transaction without interpreting its kind. A transition the site refuses MUST record no event.

#### Scenario: A release failure is recorded

- **WHEN** the lease lifecycle records a release failure with a prepared event and the site accepts the transition
- **THEN** the reservation is `release_failed` and the prepared event is recorded in the same transaction

#### Scenario: A stale release failure is refused

- **WHEN** the lease lifecycle records a release failure with a prepared event for a reservation an operator has since force-released
- **THEN** the site refuses the transition and no event is recorded
