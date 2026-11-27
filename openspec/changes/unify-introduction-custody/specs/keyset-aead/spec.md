## ADDED Requirements

### Requirement: Keyed encryption is a standalone component

The keyed-encryption component, `tools/keyset-aead`, published as `arkhai-keyset-aead`, MUST
depend on no package of this repository, only on Tink and the standard library, and MUST NOT
name any market concept, so that it can be lifted into a repository of its own as it stands. A
structure test of its own MUST refuse an import of any other distribution.

#### Scenario: A market import is added

- **WHEN** the component's source imports a package of this repository
- **THEN** its structure test fails, naming the import

### Requirement: Values are encrypted under a keyset with associated data

The component MUST encrypt a value with authenticated encryption under the primary key of a
Tink keyset, binding it to the associated data its caller supplies, and MUST decrypt a
ciphertext under whichever key of the keyset the ciphertext names. A ciphertext MUST NOT
decrypt under associated data other than that it was written with, nor under a keyset that
lacks its key; the refusal MUST be one stable error, and no error the component raises MUST
carry key material or plaintext.

#### Scenario: A value round-trips

- **WHEN** a caller encrypts a value with some associated data and decrypts the result with
  the same associated data under the same keyset
- **THEN** it reads the original value

#### Scenario: A ciphertext is presented with other associated data

- **WHEN** a caller decrypts a ciphertext with associated data other than that it was written
  with
- **THEN** decryption is refused with the component's decryption error, and the error carries
  neither the value nor any key material

#### Scenario: A ciphertext written under a retained key is read

- **WHEN** a keyset's primary key has changed and it still holds the key an older ciphertext
  names
- **THEN** the older ciphertext decrypts

### Requirement: A ciphertext's key id is readable without decrypting

The component MUST report the id of the key a ciphertext names, read from the ciphertext's
prefix without decrypting it, and MUST report a keyset's key ids and its primary key id, so a
caller can count what each key holds and name a key its keyset lacks.

#### Scenario: A stored ciphertext names a key the keyset lacks

- **WHEN** a caller reads the key id of a ciphertext written under a key since removed from
  the keyset
- **THEN** the component reports that key's id, and it is absent from the keyset's key ids

### Requirement: Only keysets whose ciphertexts name their key are admitted

Loading a keyset MUST refuse one that is empty or malformed, one whose keys are not AES-256-GCM
AEAD keys, one with no enabled primary key, and one holding a key whose ciphertexts would
carry no key id. The refusal MUST say which and MUST NOT carry key material.

#### Scenario: A keyset holds a key with no prefix

- **WHEN** a caller loads a keyset holding a key whose output prefix is raw
- **THEN** loading is refused, saying a key's ciphertexts would name no key

#### Scenario: Malformed keyset text is loaded

- **WHEN** a caller loads text that is not a keyset
- **THEN** loading is refused, and the refusal does not echo the text

### Requirement: Re-encryption is verified

The component MUST re-encrypt a ciphertext not written under the keyset's primary key by
decrypting it, encrypting the value under the primary key with the same associated data,
decrypting the result and comparing it with the original value, returning the new ciphertext
only when they are equal, and MUST report a ciphertext already under the primary key as
needing nothing.

#### Scenario: A ciphertext under a retired primary is re-encrypted

- **WHEN** a caller re-encrypts a ciphertext written under a key that is no longer primary
- **THEN** it receives a ciphertext naming the primary key, which decrypts with the same
  associated data to the original value

#### Scenario: A ciphertext already under the primary is re-encrypted

- **WHEN** a caller re-encrypts a ciphertext written under the primary key
- **THEN** the component reports that nothing needs re-encrypting
