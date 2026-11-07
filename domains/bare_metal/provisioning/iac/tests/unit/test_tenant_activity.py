"""Tenant activity policies through injected host-command boundaries."""
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from tenant_activity import ActivityError, TenantActivity


class Host:
    def __init__(self):
        self.calls = []
        self.active = True
        self.cron = True
        self.jobs = True
        self.refuse = None

    def __call__(self, argv):
        self.calls.append(argv)
        if self.refuse == argv[:2]:
            return CompletedProcess(argv, 2, '', 'observation denied')
        command = argv[0]
        if command == 'loginctl':
            if argv[1] == 'list-sessions':
                out = '1 41000 tenant_a seat0 tty1\n' if self.active else ''
            elif argv[1] == 'list-users':
                out = '41000 tenant_a\n' if self.active else ''
            else:
                out = ''
        elif command == 'systemctl':
            out = 'LoadState=not-found\nActiveState=inactive\n' if 'atd.service' in argv else 'inactive\n'
        elif command == 'pgrep':
            return CompletedProcess(argv, 0 if self.active else 1, '123\n' if self.active else '', '')
        elif command == 'pkill':
            self.active = False
            out = ''
        elif command == 'crontab':
            if argv[-1] == '-r':
                self.cron = False
                out = ''
            elif self.cron:
                out = '* * * * * echo fixture\n'
            else:
                return CompletedProcess(argv, 1, '', 'no crontab for tenant_a\n')
        elif command == 'atq':
            out = ('1 Thu Jan 1 00:00:00 2026 a tenant_a\n' if self.jobs else '') + '2 Thu Jan 1 00:00:00 2026 a neighbour\n'
        elif command == 'atrm':
            assert argv == ['atrm', '1']
            self.jobs = False
            out = ''
        else:
            raise AssertionError(argv)
        return CompletedProcess(argv, 0, out, '')


def activity(host, tmp_path):
    return TenantActivity('tenant_a', 41000, run=host, find=lambda cmd: cmd,
                          linger_root=tmp_path, cron_roots=(tmp_path,), at_roots=(tmp_path,))


def test_every_activity_is_removed_and_independently_verified(tmp_path):
    host = Host()
    result = activity(host, tmp_path).terminate()
    assert result == {'tenant_uid': 41000, 'sessions_ended': 1, 'linger_disabled': True,
                      'processes_killed': 1, 'crontab_removed': True,
                      'at_jobs_removed': 1, 'activity_terminated': True}
    assert host.calls.index(['loginctl', 'terminate-user', '41000']) < host.calls.index(['pkill', '-KILL', '-u', '41000'])
    assert host.calls.count(['pgrep', '-u', '41000']) == 2
    assert host.calls.count(['crontab', '-u', 'tenant_a', '-l']) == 2
    assert host.calls.count(['atq']) == 2


@pytest.mark.parametrize('failed', [['loginctl', 'list-sessions'], ['loginctl', 'list-users'],
                                   ['loginctl', 'terminate-user'], ['loginctl', 'disable-linger'],
                                   ['pgrep', '-u'], ['pkill', '-KILL'], ['crontab', '-u'],
                                   ['systemctl', 'show']])
def test_failed_observations_or_mutations_never_claim_success(tmp_path, failed):
    host = Host()
    host.refuse = failed
    with pytest.raises(ActivityError):
        activity(host, tmp_path).terminate()


@pytest.mark.parametrize('retained', ['linger', 'cron', 'at'])
def test_retained_scheduled_activity_fails(tmp_path, retained):
    host = Host()
    engine = activity(host, tmp_path)
    if retained == 'linger':
        (tmp_path / 'tenant_a').touch()
    elif retained == 'cron':
        original = host.__call__
        def refuse_remove(argv):
            if argv == ['crontab', '-u', 'tenant_a', '-r']:
                return CompletedProcess(argv, 0, '', '')
            return original(argv)
        engine.run = refuse_remove
    else:
        original = host.__call__
        def refuse_remove(argv):
            if argv[0] == 'atrm':
                return CompletedProcess(argv, 0, '', '')
            return original(argv)
        engine.run = refuse_remove
    with pytest.raises(ActivityError, match='remains'):
        engine.terminate()


def test_uninstalled_schedulers_require_absent_tenant_spools(tmp_path):
    host = Host()
    engine = activity(host, tmp_path)
    engine.find = lambda cmd: None
    assert engine.terminate()['activity_terminated']
    (tmp_path / 'tenant_a').touch()
    with pytest.raises(ActivityError, match='retained tenant spool'):
        engine.cron()


def test_unknown_cron_failure_is_not_no_crontab(tmp_path):
    host = Host()
    engine = activity(host, tmp_path)
    engine.run = lambda argv: CompletedProcess(argv, 1, '', 'permission denied')
    with pytest.raises(ActivityError, match='cannot observe'):
        engine.cron()


@pytest.mark.parametrize("survivor", ["process", "session", "manager"])
def test_surviving_activity_refuses_the_barrier_without_waiting(tmp_path, survivor):
    host = Host()
    original = host.__call__
    def run(argv):
        result = original(argv)
        if survivor == "process" and argv[0] == "pgrep":
            return CompletedProcess(argv, 0, '123\n', '')
        if survivor == "session" and argv[:2] == ['loginctl', 'list-sessions']:
            return CompletedProcess(argv, 0, '1 41000 tenant_a seat0 tty1\n', '')
        if survivor == "manager" and argv[0] == 'systemctl':
            return CompletedProcess(argv, 0, 'active\n', '')
        return result
    engine = activity(host, tmp_path)
    engine.run = run
    engine.settle_timeout = 0
    with pytest.raises(ActivityError, match='remain'):
        engine.terminate()


def test_missing_at_tools_with_live_daemon_is_failed_observation(tmp_path):
    host = Host()
    engine = activity(host, tmp_path)
    engine.find = lambda name: None
    engine.run = lambda argv: CompletedProcess(argv, 0, 'LoadState=loaded\nActiveState=active\n', '')
    with pytest.raises(ActivityError, match='inactive scheduler'):
        engine.at_jobs()


def test_numeric_absent_account_seam_uses_uid_and_stops_user_manager(tmp_path):
    host = Host()
    host.cron = False
    engine = activity(host, tmp_path)
    engine.account_absent = True
    result = engine.terminate()
    assert result['tenant_uid'] == 41000
    assert ['loginctl', 'terminate-session', '1'] in host.calls
    assert ['systemctl', 'stop', 'user@41000.service'] in host.calls
    assert not any(row[0] == 'crontab' for row in host.calls)
