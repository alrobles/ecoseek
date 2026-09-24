"""EcoSeek World — frozen replay runner (agent-free validation evidence).

Executes ``artifact.executable`` with zero LLM in the loop, captures logs +
metrics under ``runs/<run_id>/`` inside the world dir, and returns replay
evidence shaped for ``world_validate``: ``{run_id, exit_code, holdout}``.

This is the deterministic half of ADR-007's double gate: the world replays the
artifact on held-out inputs and decides from the exit code + measured metrics —
a model never declares its own artifact validated.

Executable kinds:
  ecoagent_tool — in-process ``tools.registry.dispatch(ref, args)`` (always
                  allowed: it is the plugin's own audited toolset)
  shell         — ``shlex.split(ref)`` argv + ``--k v`` flags from args (gated)
  r_script      — ``Rscript ref + --k v`` flags from args (gated)
  slurm_job     — ``sbatch --wait ref`` with args exported as env (gated)

Gated kinds require ``ECOSEEK_WORLD_REPLAY_EXEC=1`` — replaying an artifact runs
arbitrary code, so the default is fail-closed with a clear error (same trust
class as an agent running a terminal command, but explicit).

Holdout spec (the SwarmWorld "perturbation"): ``{"name": str, "args": {...}}`` —
``args`` are merged over ``executable.args`` so the same frozen artifact runs
against inputs it never saw. Exposed to the run as ``$REPLAY_HOLDOUT`` (JSON).

Metrics contract, first match wins:
  1. ``$REPLAY_METRICS_PATH`` (``<run_dir>/metrics.json``) written by the run
  2. ``metrics.json`` left in the run cwd
  3. the last stdout line parsing as a JSON object with a ``"metrics"`` member

Env vars (beyond world.py's):
  ECOSEEK_WORLD_REPLAY_EXEC   - "1" enables gated kinds (default: disabled)
  ECOSEEK_WORLD_REPLAY_ENV    - "1" passes full os.environ minus secrets
                                (default: minimal env)
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import time

try:
    from . import world
except ImportError:  # standalone import (tests load the dir via sys.path)
    import world  # type: ignore[no-redef]

try:
    from . import world_trace
except ImportError:  # standalone import (tests load the dir via sys.path)
    import world_trace  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

_GATED_KINDS = ("shell", "r_script", "slurm_job")
_ALL_KINDS = _GATED_KINDS + ("ecoagent_tool",)
_SECRET_RE = re.compile(r"(API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)
_MAX_LOG_BYTES = 200_000
_DEFAULT_TIMEOUT_S = 600


def _runs_dir() -> str:
    return os.path.join(world._world_dir(), "runs")


def _exec_allowed(kind: str) -> tuple[bool, str]:
    if kind not in _GATED_KINDS:
        return True, ""
    if os.environ.get("ECOSEEK_WORLD_REPLAY_EXEC") == "1":
        return True, ""
    return False, (
        f"executable kind {kind!r} is gated: set ECOSEEK_WORLD_REPLAY_EXEC=1 to "
        "allow code-executing replays (fail-closed default)"
    )


def _frozen_env(run_dir: str, holdout: dict) -> dict:
    """Minimal, deterministic run environment. Secrets never propagate."""
    if os.environ.get("ECOSEEK_WORLD_REPLAY_ENV") == "1":
        env = {k: v for k, v in os.environ.items() if not _SECRET_RE.search(k)}
    else:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", run_dir),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
        }
    env.update(
        {
            "REPLAY_RUN_DIR": run_dir,
            "REPLAY_METRICS_PATH": os.path.join(run_dir, "metrics.json"),
            "REPLAY_HOLDOUT": json.dumps(holdout, ensure_ascii=False),
            "ECOSEEK_WORLD_DIR": world._world_dir(),
        }
    )
    return env


def _args_to_flags(args: dict) -> list[str]:
    """``{"species": "Q. alba", "reps": 3}`` -> ``["--species", "Q. alba", "--reps", "3"]``."""
    flags: list[str] = []
    for k, v in sorted(args.items()):
        flags.append(f"--{k}")
        flags.append(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
    return flags


def _build_command(kind: str, exe: dict, args: dict, env: dict):
    """Return ``(argv, display)`` for subprocess kinds, or ``(None, reason)``."""
    ref = exe.get("ref")
    if not ref or not isinstance(ref, str):
        return None, "executable.ref is required"
    flags = _args_to_flags(args)
    if kind == "shell":
        argv = shlex.split(ref) + flags
    elif kind == "r_script":
        argv = ["Rscript", ref] + flags
    elif kind == "slurm_job":
        if shutil.which("sbatch") is None:
            return None, "slurm_job replay requires sbatch on PATH"
        # args go in as SLURM_EXPORT env vars, not argv: the script reads them.
        for k, v in args.items():
            env[f"REPLAY_ARG_{k}"] = (
                v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            )
        argv = ["sbatch", "--wait", "--parsable", ref]
    else:
        return None, f"kind {kind!r} is not a subprocess kind"
    if not argv or not argv[0]:
        return None, "empty command after parsing executable.ref"
    if shutil.which(argv[0]) is None and not os.path.exists(argv[0]):
        return None, f"command not found: {argv[0]}"
    return argv, " ".join(shlex.quote(a) for a in argv)


def _extract_metrics(run_dir: str, stdout_text: str) -> dict:
    """Metrics contract: $REPLAY_METRICS_PATH > ./metrics.json > last JSON line."""
    for candidate in (
        os.path.join(run_dir, "metrics.json"),
        os.path.join(run_dir, "cwd", "metrics.json"),
    ):
        try:
            with open(candidate) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return (
                    data.get("metrics")
                    if isinstance(data.get("metrics"), dict)
                    else data
                )
        except (OSError, ValueError):
            continue
    for line in reversed(stdout_text.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data.get("metrics"), dict):
            return data["metrics"]
        if isinstance(data, dict):
            return data
    return {}


def _dispatch_ecoagent_tool(ref: str, args: dict) -> tuple[int, str, str]:
    """In-process registry dispatch — the plugin's own audited toolset."""
    try:
        from tools.registry import registry
    except ImportError:
        return 2, "", "ecoagent_tool replay requires the hermes tools.registry runtime"
    try:
        result = registry.dispatch(ref, args)
    except Exception as exc:  # dispatch already error-wraps; this is belt
        return 1, "", f"dispatch raised {type(exc).__name__}: {exc}"
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    try:
        payload = json.loads(text)
        if isinstance(payload, dict) and payload.get("error"):
            return 1, "", text
    except ValueError:
        pass
    return 0, text, ""


def _truncate(data: str) -> tuple[str, bool]:
    if len(data.encode("utf-8", errors="replace")) > _MAX_LOG_BYTES:
        return data[:_MAX_LOG_BYTES] + "\n[log truncated]", True
    return data, False


def replay(
    artifact_id: str,
    holdout: dict | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    agent: str | None = None,
    task_id: str = "",
) -> dict:
    """Run ``artifact.executable`` agent-free and return replay evidence.

    Returns ``{success, run_id, exit_code, holdout, metrics, run_dir, ...}`` —
    feed ``run_id``/``exit_code``/``holdout`` into ``world_validate`` and
    ``metrics`` into its metrics argument to promote ``installed`` artifacts.
    """
    rec = world.get(artifact_id, include_events=False)
    if not rec.get("success"):
        return rec
    artifact = rec["artifact"]
    exe = artifact.get("executable") or {}
    kind = exe.get("kind")
    if kind not in _ALL_KINDS:
        return {
            "success": False,
            "error": f"unsupported executable kind {kind!r}",
            "allowed": list(_ALL_KINDS),
        }
    ok, why = _exec_allowed(kind)
    if not ok:
        return {"success": False, "error": why}

    holdout = holdout or {}
    args = {**(exe.get("args") or {}), **(holdout.get("args") or {})}
    holdout_name = holdout.get("name") or "default"

    run_id = f"replay-{artifact_id[:8]}-{int(time.time())}-{os.getpid()}"
    run_dir = os.path.join(_runs_dir(), run_id)
    work_dir = os.path.join(run_dir, "cwd")
    os.makedirs(work_dir, exist_ok=True)
    env = _frozen_env(run_dir, holdout)

    started = time.time()
    with world_trace.span(
        "replay", artifact_id=artifact_id, kind=kind, holdout=holdout_name
    ) as attrs:
        if kind == "ecoagent_tool":
            exit_code, out, err = _dispatch_ecoagent_tool(exe.get("ref"), args)
            display = f"ecoagent_tool:{exe.get('ref')}"
        else:
            argv, display = _build_command(kind, exe, args, env)
            if argv is None:
                return {"success": False, "error": display}
            out = err = ""
            try:
                proc = subprocess.run(
                    argv,
                    check=False,
                    capture_output=True,
                    timeout=timeout_s,
                    env=env,
                    cwd=work_dir,
                    text=True,
                    errors="replace",
                )
                exit_code, out, err = (
                    proc.returncode,
                    proc.stdout or "",
                    proc.stderr or "",
                )
            except subprocess.TimeoutExpired as exc:
                exit_code = 124
                out = (
                    exc.stdout.decode("utf-8", "replace")
                    if isinstance(exc.stdout, bytes)
                    else (exc.stdout or "")
                )
                err = f"[timeout after {timeout_s}s]"
            except OSError as exc:
                exit_code = 127
                err = f"spawn failed: {exc}"
        attrs["run_id"] = run_id
        attrs["exit_code"] = exit_code
    duration_ms = int((time.time() - started) * 1000)

    metrics = _extract_metrics(run_dir, out)
    out_log, out_trunc = _truncate(out)
    err_log, err_trunc = _truncate(err)

    evidence = {
        "run_id": run_id,
        "artifact_id": artifact_id,
        "kind": kind,
        "command": display,
        "exit_code": exit_code,
        "holdout": holdout_name,
        "holdout_args": holdout.get("args") or {},
        "metrics": metrics,
        "duration_ms": duration_ms,
        "agent": agent or os.environ.get("ECOSEEK_AGENT_ID", "emily"),
        "task_id": task_id,
        "log_truncated": out_trunc or err_trunc,
        "ts": started,
    }
    try:
        with open(os.path.join(run_dir, "replay.json"), "w") as f:
            json.dump(evidence, f, indent=2, ensure_ascii=False)
        with open(os.path.join(run_dir, "command.txt"), "w") as f:
            f.write(display + "\n")
        with open(os.path.join(run_dir, "stdout.log"), "w") as f:
            f.write(out_log)
        with open(os.path.join(run_dir, "stderr.log"), "w") as f:
            f.write(err_log)
    except OSError as exc:
        logger.warning("replay evidence write failed for %s: %s", run_id, exc)

    return {
        "success": True,
        "run_id": run_id,
        "exit_code": exit_code,
        "holdout": holdout_name,
        "metrics": metrics,
        "duration_ms": duration_ms,
        "run_dir": run_dir,
        "replay": {"run_id": run_id, "exit_code": exit_code, "holdout": holdout_name},
        "stdout_tail": out_log[-2000:],
        "stderr_tail": err_log[-2000:],
    }


def replay_and_validate(
    artifact_id: str,
    holdout: dict | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    gate: dict | None = None,
    agent: str | None = None,
    task_id: str = "",
) -> dict:
    """Frozen replay + validate in one call. ``gate`` is an optional
    {metric: minimum} mapping — any metric below its floor blocks validation
    even when exit_code == 0 (the world decides, not the runner)."""
    rep = replay(
        artifact_id, holdout=holdout, timeout_s=timeout_s, agent=agent, task_id=task_id
    )
    if not rep.get("success"):
        return rep
    metrics = rep["metrics"]
    gate_failures = [
        f"{k}={metrics.get(k)!r} below gate {v}"
        for k, v in (gate or {}).items()
        if not isinstance(metrics.get(k), (int, float)) or metrics[k] < v
    ]
    if rep["exit_code"] == 0 and metrics and not gate_failures:
        val = world.validate(
            artifact_id, metrics, rep["replay"], agent=agent, task_id=task_id
        )
        rep["validation"] = val
    else:
        rep["validation"] = {
            "success": False,
            "skipped": True,
            "reason": (
                "; ".join(gate_failures)
                if gate_failures
                else (
                    "no metrics produced"
                    if rep["exit_code"] == 0
                    else f"exit_code={rep['exit_code']}"
                )
            ),
        }
    return rep
