#!/usr/bin/env bash
# Shared environment for project scripts. Source it; it changes nothing outside this shell.
# A project-local Docker config is used so that a stale Docker Desktop credential
# helper in ~/.docker/config.json cannot break image pulls.
if [ -n "${BASH_VERSION:-}" ]; then _env_self="${BASH_SOURCE[0]}"; else _env_self="${(%):-%x}"; fi
PROJECT_ROOT="$(cd "$(dirname "$_env_self")/.." && pwd)"
unset _env_self
export PROJECT_ROOT
export DOCKER_CONFIG="$PROJECT_ROOT/.docker-local"
export COLIMA_PROFILE="${COLIMA_PROFILE:-hdfsopt}"
if [ -S "$HOME/.colima/$COLIMA_PROFILE/docker.sock" ]; then
  export DOCKER_HOST="unix://$HOME/.colima/$COLIMA_PROFILE/docker.sock"
fi
