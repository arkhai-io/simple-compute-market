- Schema-vector generation against partially refreshed internal wheels produced stale snapshots; all producer wheels must be rebuilt and reinstalled before generation, followed by source/wheel/installed parity checks.

- Installed-wheel qualification requires runnable Helm/OpenSpec executables; unselected shims and cached packages without assembled dependencies can fail before validation starts.

- General declaration publication was qualified through the CLI while its Helm chart still selected only the historical loader.
