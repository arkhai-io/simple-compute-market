"""Native Ansible reclaim barriers with synthetic local state.

The tests execute packaged role tasks; local stand-ins are only external host
boundaries. They neither prepare a host nor qualify real tenant termination.
"""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

from test_frp_proxy_wait import ANSIBLE_PLAYBOOK, CALLBACK, UNAVAILABLE, _ansible_env

ROOT = Path(__file__).resolve().parents[1]
BARE = ROOT.parents[2] / 'domains/bare_metal/provisioning/iac/ansible/roles/bare-metal-access'


def play(tasks, variables):
    with tempfile.TemporaryDirectory() as work:
        path = Path(work) / 'play.yaml'
        path.write_text(yaml.safe_dump([{'hosts': 'localhost', 'gather_facts': False,
                                         'connection': 'local', 'vars': variables, 'tasks': tasks}]))
        run = subprocess.run([ANSIBLE_PLAYBOOK, '-i', 'localhost,', str(path)],
                             env={**_ansible_env(), 'ANSIBLE_STDOUT_CALLBACK': CALLBACK,
                                  'ANSIBLE_LOG_PATH': '/dev/null'},
                             capture_output=True, text=True, cwd=work, timeout=90, check=False)
        start = run.stdout.find('{')
        if start < 0:
            raise AssertionError(run.stdout + run.stderr)
        return run, json.loads(run.stdout[start:])


@unittest.skipIf(ANSIBLE_PLAYBOOK is None, UNAVAILABLE)
class TestReclaimBarriers(unittest.TestCase):
    def test_missing_and_unreadable_config_fail_the_actual_removal_task(self):
        task = yaml.safe_load((ROOT / 'ansible/roles/relay-proxy/tasks/remove.yml').read_text())[0]
        with tempfile.TemporaryDirectory() as work:
            config = Path(work) / 'frpc-buyers.toml'
            for state in ('missing', 'unreadable'):
                with self.subTest(state=state):
                    if state == 'unreadable':
                        config.write_text('webServer.port = 600\n')
                        config.chmod(0)
                    run, report = play([task], {'relay_client_config': str(config),
                        'relay_proxy_teardown_library': str(ROOT / 'ansible/roles/relay-proxy/files/remove_proxy.sh'),
                        'relay_proxy_name': 'synthetic-tenant'})
                    self.assertNotEqual(run.returncode, 0, report)
                    self.assertEqual(report['stats']['localhost']['failures'], 1)
                    if config.exists():
                        config.chmod(0o600)

    def test_absent_account_is_successful_for_every_policy(self):
        for policy in ('remove_lease_key', 'lock_user', 'delete_user'):
            with self.subTest(policy=policy):
                run, report = play([{'ansible.builtin.include_role': {'name': str(BARE)}}], {
                    'node_action': 'node_reclaim_access', 'node_host_id': 'synthetic-host',
                    'target_host': 'localhost', 'bare_metal_ssh_user': 'arkhai_fixture_never_created',
                    'bare_metal_reclaim_policy': policy})
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                facts = [task['hosts']['localhost'].get('ansible_facts', {})
                         for p in report['plays'] for task in p['tasks']]
                fact = next(row['node_reclaim_access_data'] for row in facts if 'node_reclaim_access_data' in row)
                self.assertFalse(fact['account_present'])
                self.assertEqual(fact['activity'], {})
                self.assertFalse(fact['account_deleted'])
                self.assertFalse(fact['account_locked'])

    def test_activity_command_failure_stops_before_account_policy(self):
        tasks = yaml.safe_load((BARE / 'tasks/main.yml').read_text())
        barrier = next(task for task in tasks if task['name'].startswith('End and verify'))
        # A refused host command must fail Ansible, never reaching the policy.
        barrier = {**barrier, 'become': False,
                   'ansible.builtin.command': {'argv': ['/bin/false']}}
        with tempfile.TemporaryDirectory() as work:
            marker = Path(work) / 'policy-reached'
            run, report = play([barrier, {'ansible.builtin.file': {'path': str(marker), 'state': 'touch'}}], {
                'node_action': 'node_reclaim_access', 'bare_metal_account_present': True,
                'bare_metal_bounded': False, 'target_host': 'localhost'})
            self.assertNotEqual(run.returncode, 0, report)
            self.assertFalse(marker.exists())
