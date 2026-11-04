#!/usr/bin/env python3
"""End a tenant's activity before applying its account reclaim policy.

Host commands are observed and verified independently: absence is a successful
observation with no entries, never a command failure. Requires Python 3.10+.
"""

import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import time


class ActivityError(RuntimeError):
    """Host activity could not be proved absent."""


def command(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=30,
                              env={**os.environ, "LC_ALL": "C"}, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ActivityError(f"cannot execute {argv[0]}") from exc


class TenantActivity:
    def __init__(self, user, uid, *, run=command, find=shutil.which,
                 linger_root=Path('/var/lib/systemd/linger'), settle_timeout=5,
                 account_absent=False, cron_roots=(Path('/var/spool/cron'), Path('/var/spool/cron/crontabs')),
                 at_roots=(Path('/var/spool/cron/atjobs'), Path('/var/spool/cron/atspool'), Path('/var/spool/at'), Path('/var/spool/atjobs'))):
        if uid <= 0 or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_.-]*', user):
            raise ActivityError('unsafe tenant identity')
        self.user, self.uid = user, uid
        self.account_absent = account_absent
        self.run, self.find = run, find
        self.settle_timeout = settle_timeout
        self.linger_root, self.cron_roots, self.at_roots = linger_root, cron_roots, at_roots

    def checked(self, argv, allowed=(0,)):
        result = self.run(argv)
        if result.returncode not in allowed:
            raise ActivityError(f"{argv[0]} observation or operation failed ({result.returncode})")
        return result

    def sessions(self):
        rows = self.checked(['loginctl', 'list-sessions', '--no-legend', '--no-pager']).stdout.splitlines()
        sessions = []
        for row in rows:
            fields = row.split()
            if len(fields) < 3 or not fields[1].isdigit():
                raise ActivityError('unrecognized loginctl session observation')
            if int(fields[1]) == self.uid:
                sessions.append(fields[0])
        return sessions

    def registered(self):
        rows = self.checked(['loginctl', 'list-users', '--no-legend', '--no-pager']).stdout.splitlines()
        users = []
        for row in rows:
            fields = row.split()
            if len(fields) < 2 or not fields[0].isdigit():
                raise ActivityError('unrecognized loginctl user observation')
            users.append(int(fields[0]))
        return self.uid in users

    def processes(self):
        # Effective and real UID both matter (for example a setuid executable).
        found = set()
        for flag in ('-u', '-U'):
            result = self.checked(['pgrep', flag, str(self.uid)], (0, 1))
            if result.returncode == 1:
                if result.stdout.strip():
                    raise ActivityError('inconsistent process observation')
                continue
            rows = result.stdout.split()
            if not rows or any(not row.isdigit() for row in rows):
                raise ActivityError('unrecognized process observation')
            found.update(rows)
        return found

    def cron(self, remove=False):
        if self.account_absent or not self.find('crontab'):
            # An uninstalled scheduler is benign only when no retained spool
            # exists for this account. Inspection errors still fail reclaim.
            for root in self.cron_roots:
                try:
                    (root / self.user).lstat()
                except FileNotFoundError:
                    continue
                raise ActivityError('crontab unavailable with retained tenant spool')
            return False
        result = self.checked(['crontab', '-u', self.user, '-l'], (0, 1))
        if result.returncode == 1:
            if result.stdout.strip() or result.stderr.strip() != f'no crontab for {self.user}':
                raise ActivityError('cannot observe tenant crontab')
            return False
        if remove:
            self.checked(['crontab', '-u', self.user, '-r'])
        return True

    def at_jobs(self):
        if not self.find('atq'):
            state = self.checked(['systemctl', 'show', 'atd.service',
                                  '--property=LoadState', '--property=ActiveState']).stdout
            fields = dict(row.split('=', 1) for row in state.splitlines() if '=' in row)
            if (fields.get('LoadState') not in ('loaded', 'not-found')
                    or fields.get('ActiveState') not in ('inactive', 'failed')):
                raise ActivityError('at queue unavailable without an inactive scheduler')
            for root in self.at_roots:
                try:
                    entries = list(root.iterdir())
                except FileNotFoundError:
                    continue
                for entry in entries:
                    if entry.stat().st_uid == self.uid:
                        raise ActivityError('atq unavailable with retained tenant jobs')
            return []
        if self.account_absent:
            for root in self.at_roots:
                try:
                    entries = list(root.iterdir())
                except FileNotFoundError:
                    continue
                if any(entry.stat().st_uid == self.uid for entry in entries):
                    raise ActivityError('retained tenant at spool after account removal')
        jobs = []
        for row in self.checked(['atq']).stdout.splitlines():
            fields = row.split()
            if len(fields) < 3 or not fields[0].isdigit():
                raise ActivityError('unrecognized at queue observation')
            if fields[-1] in (self.user, str(self.uid)):
                jobs.append(fields[0])
        return jobs

    def terminate(self):
        sessions = self.sessions()
        registered = self.registered()
        if self.account_absent:
            # A trusted numeric caller can revoke activity after NSS removal.
            # Session ids and the user unit still carry the recorded UID.
            for session in sessions:
                self.checked(['loginctl', 'terminate-session', session])
            self.checked(['systemctl', 'stop', f'user@{self.uid}.service'])
            try:
                (self.linger_root / self.user).unlink()
            except FileNotFoundError:
                pass
        else:
            if registered:
                self.checked(['loginctl', 'terminate-user', str(self.uid)])
            self.checked(['loginctl', 'disable-linger', self.user])
        processes = self.processes()
        for flag in ('-u', '-U'):
            self.checked(['pkill', '-KILL', flag, str(self.uid)], (0, 1))
        cron = self.cron(remove=True)
        jobs = self.at_jobs()
        if jobs:
            self.checked(['atrm', *jobs])
        # Process exit and systemd teardown are asynchronous. Re-observe within
        # a bounded settling period; no mutation is allowed past this barrier.
        deadline = time.monotonic() + self.settle_timeout
        while True:
            remaining = self.processes()
            active_sessions = self.sessions()
            manager = self.checked(['systemctl', 'show', f'user@{self.uid}.service',
                                    '--property=ActiveState', '--value']).stdout.strip()
            if manager not in ('inactive', 'failed', 'active', 'activating', 'deactivating', 'reloading'):
                raise ActivityError('unrecognized user manager state')
            if not remaining and not active_sessions and manager in ('inactive', 'failed'):
                break
            if time.monotonic() >= deadline:
                raise ActivityError('tenant processes, sessions or user manager remain')
            time.sleep(0.1)
        try:
            (self.linger_root / self.user).lstat()
        except FileNotFoundError:
            pass
        else:
            raise ActivityError('tenant lingering remains enabled')
        if self.cron() or self.at_jobs():
            raise ActivityError('tenant scheduled activity remains')
        return {'tenant_uid': self.uid, 'sessions_ended': len(sessions),
                'linger_disabled': True, 'processes_killed': len(processes),
                'crontab_removed': cron, 'at_jobs_removed': len(jobs),
                'activity_terminated': True}


def main():
    numeric = len(sys.argv) == 4 and sys.argv[1] == '--trusted-uid'
    args = sys.argv[2:] if numeric else sys.argv[1:]
    if len(args) != 2 or os.geteuid() != 0:
        raise ActivityError('root must supply tenant account and observed UID')
    user, uid = args[0], int(args[1])
    try:
        account = pwd.getpwnam(user)
    except KeyError:
        if not numeric:
            raise ActivityError('tenant account lookup failed') from None
        account = None
    try:
        numeric_account = pwd.getpwuid(uid)
    except KeyError:
        numeric_account = None
    if numeric_account is not None and numeric_account.pw_name != user:
        raise ActivityError('tenant UID belongs to another account')
    # Numeric mode is an interface for an independently authorized protected
    # receipt. This helper neither creates such receipts nor authenticates one.
    if account is not None and account.pw_uid != uid:
        raise ActivityError('tenant account identity changed')
    print(json.dumps(TenantActivity(user, uid, account_absent=account is None).terminate()))


if __name__ == '__main__':
    try:
        main()
    except (ActivityError, OSError, KeyError, ValueError) as exc:
        print(f'tenant activity termination failed: {exc}', file=sys.stderr)
        sys.exit(1)
