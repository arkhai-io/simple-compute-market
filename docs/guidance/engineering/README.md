---
tags: [engineering]
---

# Engineering guidance

Guidance that holds in a repository using neither the change workflow nor OpenSpec:
how tests are placed and written, how comments and documents describe the system,
how code is composed, configured, packaged, and deployed. Each file states its rules
with neutral examples; a repository applying a rule states its own instance in its
own documents and cites the file here. These files link only to each other, so the
layer reads whole without anything above it.

## How the files are organized

The files sit flat in this directory, each named by its subject. A rule that has a
neutral principle and a form particular to one language or tool is two files: the
principle in the file named by its subject, and the form in a file named by the
subject and the tool, such as `testing.md` and `testing-python.md`, so a repository
in another language reads the principle without the form. The directory is
organization for people navigating the tree and carries no meaning: a file's
frontmatter alone states its layer and its tags. Directories may nest once the files
grow too many to navigate, named for their organization rather than after the tags
of the files within.

## Tags

Every file carries YAML frontmatter whose `tags` hold `engineering` and only tags
from this table. A `topic` tag names a subject of the work;
a `tool` tag names a tool a developer, a build, or a deployment runs, and a library
the code imports carries its language's tag.

| Tag | Kind | Description |
|---|---|---|
| `engineering` | layer | Holds in a repository that uses neither the change workflow nor OpenSpec |
| `testing` | topic | Test levels, the coverage between them, seams, doubles, and determinism |
| `dependencies` | topic | Imports and declared dependencies, and where a package belongs |
| `persistence` | topic | Stored representations, schema changes, migrations, and cutovers |
| `python` | tool | The Python language and the libraries Python code imports |
| `helm` | tool | Helm charts, values, and render tests |
| `ansible` | tool | Ansible playbooks and roles |
