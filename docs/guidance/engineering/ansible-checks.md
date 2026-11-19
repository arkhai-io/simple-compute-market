---
tags: [engineering, testing, ansible]
---

# Ansible syntax checks

`ansible-playbook --syntax-check` does not follow `include_tasks`, so checking a
role's own playbook leaves the task files it includes unparsed. A role that reaches
its task files through `include_tasks` gets a parse-only playbook that imports each
of them through `import_role` instead, in the role's context, and the syntax check
runs over that playbook too. Parsing is where some errors only show: Ansible splits a
free-form `shell: |` string as module arguments, so an unbalanced quote — an
apostrophe in a shell comment included — fails the whole task file as it loads,
though the shell would run the script. A syntax check templates nothing and executes
nothing.

A parse-only playbook's first task refuses to run and is tagged `always`, since the
tasks it imports keep their own tags and some may carry `always`: under any `--tags`
selection the refusal still runs first. An operator's explicit `--skip-tags always`
or `--start-at-task` passes over it, which nothing in a play can refuse.
