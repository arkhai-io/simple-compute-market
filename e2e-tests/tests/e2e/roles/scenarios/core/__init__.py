"""Chain-only scenarios: each reaches only the dev chain and its deployments,
and messages no storefront or provisioning service, so it meets none of the
timers a lane selecting it holds. The lane-hold check
(``tests/unit/test_scenario_lane_holds.py``) exempts this directory; a scenario
that messages a service belongs in its lane's directory instead.
"""
