#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Record deploy event with Git SHA + HTTP smoke validation."""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_release_state():
    spec = importlib.util.spec_from_file_location("release_state", ROOT / "tools" / "release_state.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    rs = _load_release_state()
    parser = argparse.ArgumentParser(description="Record CPS deploy with smoke verification")
    parser.add_argument("--commit", default="", help="Deployment commit SHA (default HEAD)")
    parser.add_argument("--server-head", default="", help="Server HEAD after deploy (default same as commit)")
    parser.add_argument("--target-server", default="CPS-PROD")
    parser.add_argument("--smoke-url", default="http://127.0.0.1:8080/giris")
    parser.add_argument("--no-restart", action="store_true")
    parser.add_argument("--rollback-commit", default="")
    args = parser.parse_args()

    try:
        manifest = rs.write_verified_manifest(
            deployment_commit=args.commit or None,
            server_head=args.server_head or None,
            target_server=args.target_server,
            server_restart=not args.no_restart,
            smoke_url=args.smoke_url,
            rollback_commit=args.rollback_commit,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"DEPLOY_RECORD_FAIL {exc}", file=sys.stderr)
        state = rs.generate_state()
        rs.atomic_write(rs.STATE_PATH, state)
        return 1

    state = rs.generate_state()
    rs.atomic_write(rs.STATE_PATH, state)
    print(f"DEPLOY_RECORD_OK commit={manifest.get('deployment_commit', '')[:8]}")
    print(f"  smoke={manifest.get('http_smoke_result')} code={manifest.get('http_smoke_status_code')}")
    print(f"  global_state={state.get('global_state')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
