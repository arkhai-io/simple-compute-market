.PHONY: test test-alkahest test-config test-identity test-policy

test: test-alkahest test-config test-identity test-policy

test-alkahest:
	cd alkahest && make test

test-config:
	cd config && make test

test-identity:
	cd identity && make test

test-policy:
	cd policy && make test
