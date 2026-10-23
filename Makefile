# Convenience targets for the 30-minute path. PROFILE is the profile name
# from `wax config init --profile <name>`.
PROFILE ?= eval

.PHONY: preflight up down tunnel domains push fire verify reset test

preflight:          ## check wax, docker, node and the profile
	./scripts/preflight.sh $(PROFILE)

up:                 ## domain server + tunnel
	docker compose up -d --build

down:
	docker compose down

tunnel:             ## print the public base URL for EVAL_DOMAIN_BASE_URL
	./scripts/tunnel_url.sh

domains:            ## register the things domain (reads .env)
	./domains/push_domains.sh $(PROFILE)

push:               ## push every agent
	./scripts/push_all.sh $(PROFILE)

fire:               ## fire every reviewer once and print the run ids
	./scripts/fire_all.sh $(PROFILE)

verify:             ## table: agent, run status, domain calls, identity verified
	python3 scripts/verify.py --profile $(PROFILE)

reset:              ## wipe the domain server's things + calls
	./scripts/reset.sh

test:               ## anti-rot: README commands exist, manifests load
	python3 -m pytest tests -q
	cd identity/node && node --test
