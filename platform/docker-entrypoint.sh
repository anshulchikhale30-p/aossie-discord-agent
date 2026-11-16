#!/bin/sh
set -eu

run_step() {
  enabled="${1:-false}"
  shift
  case "$enabled" in
    true|1|yes|TRUE|YES)
      echo "Running: $*"
      "$@"
      ;;
  esac
}

run_step "${RUN_MIGRATIONS:-false}" ./node_modules/.bin/tsx src/db/migrate.ts
run_step "${RUN_SEED:-false}" ./node_modules/.bin/tsx src/db/seed.ts
run_step "${RUN_WORKFLOW_BOOTSTRAP:-false}" ./node_modules/.bin/bootstrap

exec "$@"
