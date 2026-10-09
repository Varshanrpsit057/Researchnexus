#!/bin/sh
# Container entrypoint. Runs the given command (uvicorn by default) as PID 1
# via exec, so SIGTERM from the orchestrator reaches uvicorn and it shuts
# down cleanly (unfinished jobs are marked as cut off; app/jobs/runners.py).
#
#   migrate   apply database migrations (alembic upgrade head) and exit --
#             the deploy runs this once, as its own task, before new
#             containers start; it never drops or rewrites data.
#   check     validate the configuration (names what's missing, never a value) and exit.
set -eu

case "${1:-}" in
  migrate)
    exec python -m alembic upgrade head
    ;;
  check)
    exec python -c "from app.config import get_settings; from app.startup_checks import enforce; [print(f'warning: {f.variable}: {f.problem}') for f in enforce(get_settings())]; print('configuration ok')"
    ;;
esac

exec "$@"
