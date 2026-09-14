#!/usr/bin/env python3
"""
pprof-analyzer orchestration script.

Orchestrates the GitHub Action flow: trigger → poll → convert → prompt → LLM
→ extract patch → apply → PR. See Config.STEP_DESCRIPTIONS for the step list.
If any step 1b-1j fails, step 2a flags the execution as error via SERVICE_URL.
"""


from __future__ import annotations

import base64
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import overload
from urllib.parse import urlparse


import git
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import litellm

from litellm.types.llms.openai import (
    AllMessageValues,
    ChatCompletionAssistantMessage,
    ChatCompletionToolParam,
)
from litellm.types.utils import ChatCompletionMessageToolCall, ModelResponse




# ---------------------------------------------------------------------------
# Configuration & Constants
# ---------------------------------------------------------------------------

class Config:
    """Centralized configuration constants."""
    REQUEST_TIMEOUT_SECONDS = 60
    POLL_INTERVAL_SECONDS = 15
    POLL_TIMEOUT_SECONDS = 10 * 60
    PPROF_TO_MD_TIMEOUT_SECONDS = 60
    GIT_OPERATIONS_TIMEOUT_SECONDS = 120
    GH_CLI_TIMEOUT_SECONDS = 180
    LLM_TIMEOUT_SECONDS = 90
    LLM_NUM_RETRIES = 1
    LLM_ENDPOINT_CONNECT_TIMEOUT_SECONDS = 10

    # Total number of LLM generations attempted for a patch (1 initial +
    # retries). If the patch fails `git apply --check` or extraction, the
    # failure is fed back to the LLM for a corrective regeneration.
    MAX_PATCH_ATTEMPTS = 2

    # Maximum lines returned by a single read_file tool call. Prevents a
    # single huge file from blowing the model's context window mid-loop.
    READ_FILE_MAX_LINES = 800

    # Maximum number of read_file tool calls allowed in a single LLM agent
    # loop before the model is told to stop reading and produce an answer.
    MAX_TOOL_CALLS = 10

    ARTIFACTS_DIR = Path("artifacts")



    VALID_REFERENCES = {"low", "med", "high"}

    PATCH_FENCE_PATTERN = r"```(?:diff[a-z-]*)?\n(.*?)```"
    SUMMARY_PATTERN = r"###\s*SUMMARY\s*\n(.*?)(?:###\s*PATCH|\Z)"

    STEP_DESCRIPTIONS: dict[str, str] = {
        "0": "Pre-flight: verify AI endpoint reachable",
        "1a": "Trigger analyzer",
        "1b": "Poll analyzer result / convert pprof",
        "1c": "Prepare git checkout",
        "1d": "Generate file list (agent-loop file access)",
        "1e": "Construct prompt",
        "1f": "Feed prompt to LLM",
        "1g": "Extract git patch",
        "1h": "Apply git patch",
        "1j": "Create branch, commit, push, open PR",
        "1k": "Flag execution as submitted",
    }


class AnalyzerError(Exception):
    """Raised when a step in the 1b-1j flow fails. Carries the step label."""

    def __init__(self, step: str, message: str):
        self.step = step
        self.message = message
        super().__init__(f"[{step}] {message}")


class EnvConfig:
    """Load and validate all required environment variables at startup."""

    def __init__(self):
        self.repository = self._get_required("GITHUB_REPOSITORY")
        self.token = self._get_required("GITHUB_TOKEN")
        self.tags = self._get_required("TAGS")
        self.reference = self._get_enum("REFERENCE", Config.VALID_REFERENCES)
        self.ai_key = self._get_required("AI_KEY")
        self.ai_endpoint = self._get_required("AI_ENDPOINT")
        self.ai_model = self._get_optional("AI_MODEL", "gamma4")
        self.service_url = self._get_optional(
            "SERVICE_URL", "https://analyzer.internal/api/v1"
        ).rstrip("/")
        self.analyzer_result_file = self._get_optional("ANALYZER_RESULT_FILE", None)
        self.base_branch = self._get_optional("BASE_BRANCH", "")
        self.github_server_url = self._get_optional(
            "GITHUB_SERVER_URL", "https://github.com"
        ).rstrip("/")
        self.action_path = Path(self._get_required("ACTION_PATH"))

        self._validate()

    def _get_required(self, name: str) -> str:
        """Get required env var, raise AnalyzerError if missing."""
        value = os.environ.get(name, "").strip()
        if not value:
            raise AnalyzerError("init", f"Required env var missing: {name}")
        return value

    @overload
    def _get_optional(self, name: str, default: None = None) -> str | None: ...

    @overload
    def _get_optional(self, name: str, default: str) -> str: ...

    def _get_optional(self, name: str, default: str | None = None) -> str | None:
        """Get optional env var with default (stripped of whitespace)."""
        value = os.environ.get(name, default)
        if isinstance(value, str):
            return value.strip()
        return value


    def _get_enum(self, name: str, allowed: set) -> str:
        """Get enum env var, validate against allowed values."""
        value = self._get_required(name)
        if value.lower() not in allowed:
            raise AnalyzerError(
                "init", f"Invalid {name}: {value}. Allowed: {sorted(allowed)}"
            )
        return value.lower()

    def _validate(self) -> None:
        """Additional validation beyond basic env var checks."""
        if "/" not in self.repository:
            raise AnalyzerError(
                "init", f"Invalid GITHUB_REPOSITORY format: {self.repository}"
            )
        if not self.tags or not self.tags.strip():
            raise AnalyzerError("init", "Git reference (TAGS) is empty or whitespace")


# Tracks the status of each step: "ok", "error", or absent (not run yet).
STEP_RESULTS: dict[str, str] = {}

# Module-level lazily-created requests.Session. Reuses one connection (with
# keep-alive) across all SERVICE_URL calls instead of a fresh TLS handshake
# per request. GETs get automatic retries on 502/503/504; POSTs do not (to
# avoid creating duplicate analyzer runs).
_session: requests.Session | None = None


def _get_session() -> requests.Session:
    """Return the module-level requests.Session, creating it on first use."""
    global _session
    if _session is None:
        _session = requests.Session()
        retry_adapter = HTTPAdapter(
            max_retries=Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[502, 503, 504],
                allowed_methods=["GET"],
            )
        )
        _session.mount("https://", retry_adapter)
        _session.mount("http://", retry_adapter)
    return _session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _service_request(
    method: str,
    endpoint: str,
    step: str,
    service_url: str,
    ai_key: str,
    payload: dict | None = None,
) -> dict:
    """Make authenticated request to SERVICE_URL, raising AnalyzerError on failure.

    Uses a shared requests.Session for connection reuse. GETs are retried
    automatically on 502/503/504; POSTs are not retried (to avoid duplicate
    side effects like creating two analyzer runs).

    Args:
        method: HTTP method ("GET", "POST")
        endpoint: API endpoint path (e.g. "/runs", "/runs/{id}/submit")
        step: Step label for error reporting (e.g. "1a", "1b")
        service_url: Base URL of the analyzer service API
        ai_key: API key used as Bearer token
        payload: Optional JSON payload for POST requests

    Returns:
        Parsed JSON response dict

    Raises:
        AnalyzerError: On network error, timeout, or HTTP error
    """
    url = f"{service_url}{endpoint}"
    headers = {
        "Authorization": f"Bearer {ai_key}",
        "Content-Type": "application/json",
    }
    session = _get_session()

    try:
        if method.upper() == "GET":
            resp = session.get(url, headers=headers, timeout=Config.REQUEST_TIMEOUT_SECONDS)
        elif method.upper() == "POST":
            resp = session.post(
                url, headers=headers, json=payload, timeout=Config.REQUEST_TIMEOUT_SECONDS
            )
        else:
            raise AnalyzerError(step, f"Unsupported HTTP method: {method}")

        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        raise AnalyzerError(step, f"Request to {endpoint} failed: {exc}") from exc



def _run_command(
    cmd: list, step: str, timeout: int | None = None, error_prefix: str = ""
) -> str:

    """Run subprocess and raise AnalyzerError on non-zero exit.

    Args:
        cmd: Command and arguments as list
        step: Step label for error reporting
        timeout: Command timeout in seconds (None = no timeout)
        error_prefix: Optional prefix for error message

    Returns:
        Captured stdout as string

    Raises:
        AnalyzerError: On non-zero exit, timeout, or exception
    """
    if timeout is None:
        timeout = Config.GIT_OPERATIONS_TIMEOUT_SECONDS

    prefix_msg = f"{error_prefix}: " if error_prefix else ""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise AnalyzerError(step, f"{prefix_msg}Command failed: {result.stderr}")
        return result.stdout
    except AnalyzerError:
        raise
    except subprocess.TimeoutExpired as exc:
        raise AnalyzerError(step, f"{prefix_msg}Command timeout: {' '.join(cmd[:2])} took >{timeout}s") from exc
    except Exception as exc:
        raise AnalyzerError(step, f"{prefix_msg}Command failed: {exc}") from exc



def _ensure_artifacts_dir() -> None:
    Config.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def _write_artifact(name: str, content: str) -> Path:
    _ensure_artifacts_dir()
    path = Config.ARTIFACTS_DIR / name
    path.write_text(content, encoding="utf-8")
    return path


def _set_output(name: str, value: str) -> None:
    """Set a GitHub Actions step output."""
    # $GITHUB_OUTPUT is provided by the runner.
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def _gh_annotation(level: str, message: str, step: str = "") -> None:
    """Emit a GitHub Actions workflow command annotation.

    ``level`` must be one of ``"error"``, ``"warning"``, or ``"notice"``.
    The annotation appears in the run summary, the step log, and (for PR
    checks) the PR annotations view.

    ``step`` is an optional step label (e.g. ``"1h"``) prepended to the
    message for easy identification.
    """
    prefix = f"[{step}] " if step else ""
    # GitHub requires %, CR, and LF to be percent-encoded in workflow commands.
    safe_msg = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::{level}::{prefix}{safe_msg}")


def _record_step(step: str, status: str) -> None:
    """Record the status of a step for the step summary table."""
    STEP_RESULTS[step] = status


def _write_step_summary(run_id: str) -> None:
    """Write a markdown summary table to the GitHub Actions run summary.

    Writes to ``$GITHUB_STEP_SUMMARY`` if set (i.e. when running inside a
    GitHub Actions runner). Silently does nothing when the variable is absent
    (e.g. when running locally).
    """
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return
    lines = [
        f"## pprof-analyzer — Run `{run_id}`",
        "",
        "| Step | Description | Status |",
        "|------|-------------|--------|",
    ]
    for step, desc in Config.STEP_DESCRIPTIONS.items():
        status = STEP_RESULTS.get(step, "—")
        icon = {"ok": "✅", "error": "❌"}.get(status, "⏭️")
        lines.append(f"| {step} | {desc} | {icon} {status} |")
    Path(summary_file).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _node_bin(name: str, action_path: Path) -> str:
    """Resolve an npm-installed CLI binary from the action's local node_modules.

    Using the local pinned binary (instead of ``npx``) avoids a network
    re-resolve at runtime and guarantees the version from
    ``action/package-lock.json`` is the one that runs.
    """
    candidate = action_path / "action" / "node_modules" / ".bin" / name
    return str(candidate)



def _decode_pprof_result(result: str) -> Path:
    """Decode a base64-encoded raw pprof profile and write it to disk.

    The SERVICE_URL poll response carries the raw pprof bytes (e.g.
    ``*.pb.gz``) as a base64 string in the ``result`` field. This helper
    decodes the bytes and writes them to ``artifacts/raw_profile.pb.gz``.
    """
    _ensure_artifacts_dir()
    out_path = Config.ARTIFACTS_DIR / "raw_profile.pb.gz"
    try:
        raw_bytes = base64.b64decode(result)
    except Exception as exc:  # noqa: BLE001
        raise AnalyzerError("1b", f"Failed to base64-decode pprof result: {exc}") from exc
    if not raw_bytes:
        raise AnalyzerError("1b", "Decoded pprof result is empty.")
    out_path.write_bytes(raw_bytes)
    print(f"[1b] Wrote {len(raw_bytes)} bytes of raw pprof to {out_path}.")
    return out_path


def convert_pprof_to_markdown(pprof_path: Path, action_path: Path) -> str:
    """Convert a raw pprof profile to LLM-friendly markdown via ``pprof-to-md``.

    Uses the ``detailed`` format (full call tree with function details) and
    includes source-code context for the hot functions so the LLM can see the
    exact lines where CPU time is spent. The output is written to
    ``artifacts/analyzer_result.md`` via ``-o`` and read back.
    """
    _ensure_artifacts_dir()
    out_file = Config.ARTIFACTS_DIR / "analyzer_result.md"
    cmd = [
        _node_bin("pprof-to-md", action_path),
        "--format", "detailed",
        str(pprof_path),
        "-o", str(out_file),
    ]
    print(f"[1b] Converting pprof to markdown: {' '.join(cmd)}")
    _run_command(cmd, "1b", timeout=Config.PPROF_TO_MD_TIMEOUT_SECONDS, error_prefix="pprof-to-md")
    if not out_file.exists():
        raise AnalyzerError("1b", f"pprof-to-md did not produce output file: {out_file}")
    markdown = out_file.read_text(encoding="utf-8")
    if not markdown.strip():
        raise AnalyzerError("1b", "pprof-to-md produced empty output.")
    print(f"[1b] pprof-to-md produced {len(markdown)} chars of markdown.")
    return markdown


def list_repo_files(repo: git.Repo | None = None) -> str:
    """Generate a simple list of Go files in the repository.

    Returns a markdown list of .go files for the LLM to choose from.
    Uses git ls-files if possible, otherwise walks the filesystem.
    """
    files = []
    try:
        if repo is None:
            repo = git.Repo(os.getcwd())
        # Get tracked Go files from git
        for item in repo.git.ls_files().split('\n'):
            if item.endswith('.go'):
                files.append(item)
    except Exception:
        # Fallback: walk filesystem
        for root, dirs, filenames in os.walk('.'):
            # Skip common non-source directories
            dirs[:] = [d for d in dirs if d not in {'.git', 'vendor', 'node_modules', '.github', 'build', 'dist'}]
            for f in filenames:
                if f.endswith('.go'):
                    path = os.path.relpath(os.path.join(root, f), '.')
                    files.append(path)


    files.sort()
    return "\n".join(f"- `{f}`" for f in files)


# Cache of file contents (keyed by path) to avoid repeated `git show` subprocesses
# when the LLM re-requests the same file at a different line range. Scoped to the run.
_file_content_cache: dict[str, str] = {}


def read_file_context(file_path: str, line_range: tuple[int, int] | None = None, repo: git.Repo | None = None) -> str:
    """Read a file (or line range) from the repository, returning lines with context.

    Args:
        file_path: Path to the file (repository-relative, e.g. 'main.go' or 'pkg/utils.go')
        line_range: Tuple of (start_line, end_line) (1-indexed, inclusive). If None, returns entire file.
        repo: Git repo object. If None, creates one from current directory.

    Returns:
        The file content with line numbers prepended, or an error message if file not found.
    """
    try:
        if repo is None:
            repo = git.Repo(os.getcwd())

        # Check the content cache first to avoid a repeated `git show` subprocess.
        if file_path in _file_content_cache:
            content = _file_content_cache[file_path]
        else:
            content = None
            # Try to read from git first (most reliable in CI)
            try:
                content = repo.git.show(f"HEAD:{file_path}")
            except git.GitCommandError:
                # Fall back to filesystem
                if not os.path.exists(file_path):
                    return f"ERROR: File not found in HEAD or filesystem: {file_path}"
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                except UnicodeDecodeError:
                    return f"ERROR: File is binary or has invalid encoding: {file_path}"
                except PermissionError:
                    return f"ERROR: Permission denied reading file: {file_path}"
                except IOError as io_err:
                    return f"ERROR: Cannot read file: {file_path} ({io_err})"

            if content is not None:
                _file_content_cache[file_path] = content

        if content is None:
            return f"ERROR: File not found: {file_path}"


        # Handle both LF and CRLF line endings consistently
        lines = content.splitlines()

        if line_range:
            start, end = line_range
            # Validate line range
            if start < 1 or end < 1:
                return f"ERROR: Invalid line range ({start}-{end}). Line numbers must be >= 1."
            if start > end:
                return f"ERROR: Invalid line range ({start}-{end}). Start must be <= end."
            if start > len(lines):
                return f"ERROR: Line {start} is beyond file length ({len(lines)} lines)."

            start = max(1, start - 3)  # Include 3 lines of context before
            end = min(len(lines), end + 3)  # Include 3 lines of context after
            # Clamp the range to the max-lines cap so "1-999999" can't bypass it.
            if end - start + 1 > Config.READ_FILE_MAX_LINES:
                end = start + Config.READ_FILE_MAX_LINES - 1
            lines = lines[start - 1:end]
            start_line = start
        else:
            start_line = 1

        # Cap the total lines returned to prevent blowing the model's context window.
        truncated_marker = ""
        if len(lines) > Config.READ_FILE_MAX_LINES:
            total_lines = len(lines)
            lines = lines[:Config.READ_FILE_MAX_LINES]
            truncated_marker = (
                f"\n... [truncated: file has {total_lines} lines, showing 1-"
                f"{Config.READ_FILE_MAX_LINES}. Request a specific line_range "
                f'(e.g. "{Config.READ_FILE_MAX_LINES + 1}-{Config.READ_FILE_MAX_LINES * 2}") to see more.]'
            )

        result = []
        for i, line in enumerate(lines, start=start_line):
            # Format: "L{line_num}| {content}" to make it clearer for LLM to parse
            result.append(f"L{i}| {line}")

        return "\n".join(result) + truncated_marker

    except Exception as e:
        return f"ERROR: Failed to read {file_path}: {e}"




# ---------------------------------------------------------------------------
# Step 1a — Trigger analyzer execution
# ---------------------------------------------------------------------------

def trigger_analyzer(reference: str, tags: str, repository: str, config: EnvConfig) -> str:
    """POST /runs to authenticate and trigger the analyzer. Returns run_id."""
    payload = {
        "reference": reference,
        "tags": tags,
        "repository": repository,
    }
    data = _service_request("POST", "/runs", "1a", config.service_url, config.ai_key, payload)
    run_id = data.get("run_id")
    if not run_id:
        raise AnalyzerError("1a", f"No run_id in trigger response: {data}")
    print(f"[1a] Analyzer triggered. run_id={run_id}")
    return run_id


# ---------------------------------------------------------------------------
# Step 1b — Poll for analyzer result
# ---------------------------------------------------------------------------

def poll_analyzer_result(run_id: str, config: EnvConfig) -> Path:
    """GET /runs/{run_id} periodically until status == completed.

    The completed response carries a base64-encoded raw pprof profile
    (e.g. ``*.pb.gz``) in the ``result`` field. The bytes are decoded and
    written to ``artifacts/raw_profile.pb.gz``; the path is returned.
    """
    deadline = time.time() + Config.POLL_TIMEOUT_SECONDS
    last_status = None
    # Start at 2s and back off ×1.5 up to the 15s ceiling. Same worst case,
    # meaningfully faster for quick runs.
    interval = 2.0
    max_interval = float(Config.POLL_INTERVAL_SECONDS)

    while time.time() < deadline:
        data = _service_request("GET", f"/runs/{run_id}", "1b", config.service_url, config.ai_key)
        status = data.get("status", "unknown")
        if status != last_status:
            print(f"[1b] Polling run {run_id}: status={status}")
            last_status = status

        if status == "completed":
            result = data.get("result", "")
            if not result:
                raise AnalyzerError("1b", f"Analyzer completed but 'result' is empty: {data}")
            pprof_path = _decode_pprof_result(result)
            print(f"[1b] Analyzer completed. Raw pprof written to {pprof_path}.")
            return pprof_path
        if status == "error":
            raise AnalyzerError("1b", f"Analyzer reported error: {data}")

        # Clamp the final sleep so the loop never overshoots the deadline.
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))
        interval = min(interval * 1.5, max_interval)

    raise AnalyzerError("1b", f"Timed out after {Config.POLL_TIMEOUT_SECONDS}s waiting for run {run_id}")



# ---------------------------------------------------------------------------
# Step 1b (file mode) — Load a raw pprof profile from a local file
# ---------------------------------------------------------------------------

def load_analyzer_result_from_file(path_str: str) -> Path:
    """Load a raw pprof profile file (e.g. ``*.pb.gz``) for testing mode.

    Replaces steps 1a (trigger) and 1b (poll) when ANALYZER_RESULT_FILE is set.
    The file is expected to be a raw pprof profile, not JSON.
    """
    path = Path(path_str)
    if not path.is_file():
        raise AnalyzerError("1b", f"Analyzer result file not found: {path}")
    print(f"[1b] Loaded raw pprof profile from {path} ({path.stat().st_size} bytes).")
    return path



def local_run_id() -> str:
    """Generate a deterministic run_id for file-based (testing) runs."""
    return f"local-{int(time.time())}"


# ---------------------------------------------------------------------------
# Step 1c — Verify / prepare git checkout
# ---------------------------------------------------------------------------


def prepare_git_checkout(tags: str) -> git.Repo:
    """Ensure we are on the requested branch/tag and the repo is usable."""
    try:
        repo = git.Repo(os.getcwd())
    except git.InvalidGitRepositoryError as exc:
        raise AnalyzerError("1c", f"Not a git repository: {exc}") from exc

    if repo.head.is_detached:
        # Checking out a tag or SHA leaves the repo in detached HEAD; compare
        # the commit we're on against what `tags` resolves to (not the raw
        # tag string, which would never match a commit SHA).
        current = repo.head.commit.hexsha
        try:
            mismatched = current != repo.git.rev_parse(tags)
        except git.GitCommandError:
            mismatched = False
    else:
        current = repo.active_branch.name
        mismatched = current != tags

    print(f"[1c] Current checkout: {current} (requested: {tags})")
    if mismatched:
        # checkout already happened in the composite action; warn if mismatched.
        msg = f"Checked-out ref '{current}' differs from requested '{tags}'"
        _gh_annotation("warning", msg, "1c")
        print(f"[1c] WARNING: {msg}")
    return repo


# ---------------------------------------------------------------------------
# Step 1e — Construct prompt
# ---------------------------------------------------------------------------

def construct_prompt(template_path: Path, reference: str, analyzer_result: str, file_list: str) -> str:
    template = template_path.read_text(encoding="utf-8")
    prompt = template.format(
        reference_level=reference,
        analyzer_result=analyzer_result,
        file_list=file_list,
    )
    print(f"[1e] Prompt constructed ({len(prompt)} chars).")
    return prompt


# ---------------------------------------------------------------------------
# Step 1f — Feed to LLM
# ---------------------------------------------------------------------------

def _resolve_litellm_model(ai_model: str) -> str:
    """Map AI_MODEL to a litellm provider/model string.

    Unprefixed values (e.g. "gamma4") are assumed to target the existing
    self-hosted OpenAI-compatible endpoint and are auto-prefixed with
    "openai/" so existing configs keep working unchanged. Users targeting a
    native provider opt in by setting AI_MODEL to an already-prefixed
    litellm model string, e.g. "anthropic/claude-3-5-sonnet-20241022".
    """
    return ai_model if "/" in ai_model else f"openai/{ai_model}"


def validate_llm_endpoint(config: EnvConfig) -> None:
    """Pre-flight TCP connectivity check on the AI endpoint.

    Fails fast (~10s) on DNS/connection errors before litellm's retry cycle.
    Does not validate the API key or model name — those are left to litellm.

    Raises:
        AnalyzerError: If the endpoint is unreachable within the timeout.
    """

    parsed = urlparse(config.ai_endpoint)

    host = parsed.hostname
    if not host:
        raise AnalyzerError(
            "0", f"Invalid AI endpoint URL (no host): {config.ai_endpoint}"
        )
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        with socket.create_connection(
            (host, port), timeout=Config.LLM_ENDPOINT_CONNECT_TIMEOUT_SECONDS
        ):
            pass  # Connection succeeded — endpoint is reachable.
    except (socket.gaierror, OSError) as exc:
        raise AnalyzerError(
            "0",
            f"AI endpoint unreachable: {config.ai_endpoint} "
            f"(host={host}, port={port}) — {exc}",
        ) from exc
    print(f"[0] Pre-flight check passed: {host}:{port} is reachable.")


def call_llm(
    messages: list[AllMessageValues],
    config: EnvConfig,
    tools: list[ChatCompletionToolParam] | None = None,
    repo: git.Repo | None = None,
) -> tuple[str, list[AllMessageValues]]:

    """Call the configured LLM endpoint with the given conversation via litellm.

    If tools are provided, enables tool-use and handles tool calls in a loop.
    Returns (final_text_response, all_messages_for_context).
    """
    model = _resolve_litellm_model(config.ai_model)
    print(f"[1f] Calling LLM (model={model})...")

    tool_calls_made = 0

    while True:
        kwargs: dict = {

            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "api_key": config.ai_key,
            "api_base": config.ai_endpoint,
            "timeout": Config.LLM_TIMEOUT_SECONDS,
            "num_retries": Config.LLM_NUM_RETRIES,
            "drop_params": True,  # tolerate providers/models that reject params like `temperature`
        }

        if tools:
            kwargs["tools"] = tools
        completion = litellm.completion(**kwargs)
        # narrows for Pylance — litellm.completion() can also return
        # CustomStreamWrapper (stream=True), which we never use.
        if not isinstance(completion, ModelResponse):
            raise AnalyzerError("1f", "LLM returned unexpected response type.")


        assistant_message = completion.choices[0].message

        text = assistant_message.content or ""

        # If no tools, return the text response
        if not tools or not assistant_message.tool_calls:
            print(f"[1f] LLM returned {len(text)} chars.")
            return text, messages

        # Handle tool calls — filter to function tool calls (the only type we support).
        tool_calls = assistant_message.tool_calls
        print(f"[1f] LLM made {len(tool_calls)} tool call(s).")

        # Add the assistant's response (with tool calls) to the conversation.
        # ChatCompletionAssistantMessage narrows AllMessageValues to the
        # assistant variant so Pylance accepts the tool_calls field.
        # ChatCompletionMessageToolCall.type is typed as str | None but
        # litellm always sets it to "function" (the only type supported), so
        # we use the literal here to satisfy the TypedDict's
        # Literal["function"] requirement.
        assistant_msg: ChatCompletionAssistantMessage = {
            "role": "assistant",
            "content": text,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
                if isinstance(tc, ChatCompletionMessageToolCall)
            ],
        }
        messages.append(assistant_msg)

        # Process each tool call and add tool responses
        for i, tool_call in enumerate(tool_calls, 1):
            if not isinstance(tool_call, ChatCompletionMessageToolCall):
                continue
            tool_name = tool_call.function.name
            tool_input = tool_call.function.arguments
            tool_id = tool_call.id

            print(f"[1f] Tool call {i}/{len(tool_calls)}: {tool_name}")

            if tool_name == "read_file":
                result = _execute_read_file_tool(tool_input, repo)
                print(f"[1f]   → {len(result)} chars returned")
            else:
                result = f"ERROR: Unknown tool {tool_name}"
                print(f"[1f]   → ERROR: Unknown tool")

            # Add tool result to the conversation (role must be "tool", not "user")
            messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": result,
            })

        tool_calls_made += len(tool_calls)
        if tool_calls_made >= Config.MAX_TOOL_CALLS:
            # Tell the model it has no reads left and must answer now, rather
            # than raising and losing the whole run.
            messages.append({
                "role": "user",
                "content": (
                    f"You have used all {Config.MAX_TOOL_CALLS} read_file calls. "
                    "Stop reading files and produce your SUMMARY and PATCH now."
                ),
            })
            # Re-call the LLM without tools so it must produce a text answer.
            kwargs.pop("tools", None)
            completion = litellm.completion(**kwargs)
            if not isinstance(completion, ModelResponse):
                raise AnalyzerError("1f", "LLM returned unexpected response type after tool-call limit.")
            text = completion.choices[0].message.content or ""
            print(f"[1f] LLM returned {len(text)} chars (after tool-call limit).")
            return text, messages




def _execute_read_file_tool(tool_input: str, repo: git.Repo | None = None) -> str:
    """Execute the read_file tool request.

    tool_input can be:
    - "main.go" — read entire file
    - "main.go:100-150" — read lines 100-150
    - "utils.go:search_user" — read function (approximate by searching)

    Returns error message if the tool input is invalid or file cannot be read.
    """
    try:
        # Parse JSON arguments from the LLM
        if isinstance(tool_input, str):
            try:
                params = json.loads(tool_input)
            except json.JSONDecodeError as e:
                return f"ERROR: Invalid JSON in tool arguments: {e}. Expected: {{'file_path': '...', 'line_range': '...' (optional)}}"
        else:
            params = tool_input

        file_path = params.get("file_path", params.get("path", ""))
        raw_line_range = params.get("line_range")

        if not file_path:
            return "ERROR: No file_path provided. Use 'file_path' key in arguments."

        # Validate file_path is contained within the repository working tree.
        # Path.resolve() follows symlinks, so this also blocks a symlink inside
        # the repo pointing at /etc/shadow. An absolute path that *is* inside
        # the repo still resolves fine.
        wt_dir = repo.working_tree_dir if repo else os.getcwd()
        if wt_dir is None:
            return "ERROR: Cannot determine repository root — not allowed."
        repo_root = Path(wt_dir).resolve()
        try:
            candidate = (repo_root / file_path).resolve()
            candidate.relative_to(repo_root)  # raises ValueError if outside
        except (ValueError, OSError):
            return f"ERROR: Path '{file_path}' is outside the repository — not allowed."
        # Pass the validated repo-relative path so the `git show HEAD:<path>` branch keeps working.
        file_path = candidate.relative_to(repo_root).as_posix()


        # Parse line_range if provided as string "100-150"
        line_range: tuple[int, int] | None = None
        if isinstance(raw_line_range, str):
            if '-' not in raw_line_range:
                return f"ERROR: Invalid line_range format '{raw_line_range}'. Use 'start-end' format (e.g., '100-150')"
            try:
                start, end = raw_line_range.split('-')
                line_range = (int(start.strip()), int(end.strip()))
            except ValueError:
                return f"ERROR: Invalid line_range format '{raw_line_range}'. Use 'start-end' format (e.g., '100-150')"


        result = read_file_context(file_path, line_range, repo)
        return result


    except Exception as e:
        # Return detailed error messages to help LLM correct its requests
        error_msg = str(e)

        if "not found" in error_msg.lower() or "no such file" in error_msg.lower():
            return f"ERROR: File not found: {tool_input}. Please check the file path and try again."
        elif "permission" in error_msg.lower():
            return f"ERROR: Permission denied reading file: {tool_input}. The file exists but cannot be read."
        else:
            return f"ERROR: Failed to read file: {error_msg}"


# ---------------------------------------------------------------------------
# Step 1g — Extract git patch from LLM result
# ---------------------------------------------------------------------------

def create_read_file_tool() -> ChatCompletionToolParam:
    """Create the read_file tool definition for the LLM."""
    return {

        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file or line range from the repository. Use this to examine code before writing patches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Repository-relative path to the file (e.g., 'main.go' or 'pkg/utils.go')",
                    },
                    "line_range": {
                        "type": "string",
                        "description": "Optional line range in format 'start-end' (e.g., '100-150'). If omitted, reads entire file.",
                    },
                },
                "required": ["file_path"],
            },
        },
    }


def extract_patch(llm_result: str) -> tuple[str, str]:
    """Extract the SUMMARY section and the diff patch from the LLM result.
    Returns (summary, patch).
    """
    # Extract the diff code fence (flexible to handle variations like ```diff-python``).
    diff_match = re.search(Config.PATCH_FENCE_PATTERN, llm_result, re.DOTALL)
    if not diff_match:
        preview = llm_result[:500] if len(llm_result) > 500 else llm_result
        raise AnalyzerError("1g", f"No patch code fence found in LLM result.\nGot:\n{preview}")
    patch = diff_match.group(1).strip()
    if not patch:
        raise AnalyzerError("1g", "Extracted patch is empty.")

    # Extract the SUMMARY section.
    summary_match = re.search(Config.SUMMARY_PATTERN, llm_result, re.DOTALL | re.IGNORECASE)
    summary = summary_match.group(1).strip() if summary_match else "Automated pprof-analyzer fix."

    print(f"[1g] Extracted patch ({len(patch)} chars) and summary ({len(summary)} chars).")
    return summary, patch


# ---------------------------------------------------------------------------
# Step 1f/1g — Generate a patch, retrying once (fed the git-apply error) if
# extraction or a `git apply --check` dry-run fails.
# ---------------------------------------------------------------------------

def _git_apply_check(patch: str) -> str | None:
    """Dry-run `git apply --check` against the patch from the repository root.

    Does not mutate the working tree. Returns None if the patch would apply
    cleanly, or the captured error message otherwise (never raises).
    """
    _ensure_artifacts_dir()
    patch_file = Config.ARTIFACTS_DIR / "patch_check.diff"
    patch_file.write_text(patch + "\n", encoding="utf-8")
    try:
        result = subprocess.run(
            ["git", "apply", "--check", "--whitespace=fix", str(patch_file)],
            capture_output=True, text=True, timeout=Config.GIT_OPERATIONS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return f"git apply --check timed out after {Config.GIT_OPERATIONS_TIMEOUT_SECONDS}s"
    if result.returncode != 0:
        error_msg = result.stderr.strip() or "git apply --check failed with no stderr output"
        # If the error mentions context or indentation, provide a helpful hint
        if "context" in error_msg.lower() or "indent" in error_msg.lower():
            error_msg += "\n\nHint: This may be a whitespace issue (tabs vs spaces). " \
                         "Ensure the patch uses the same indentation as the original file."
        return error_msg
    return None


def generate_valid_patch(prompt: str, config: EnvConfig, repo: git.Repo | None = None) -> tuple[str, str, str]:
    """Call the LLM with tool-use enabled to generate a patch via agent loop.

    The LLM can use the read_file tool to request specific files/line ranges
    as needed. Once it has enough context, it produces a SUMMARY/PATCH response.

    If extraction fails or the patch fails `git apply --check`, the error is
    fed back to the LLM for correction, up to ``Config.MAX_PATCH_ATTEMPTS`` times.

    Returns (summary, patch, llm_result) from the first attempt whose patch
    checks out cleanly. Raises AnalyzerError("1h") if no attempt succeeds.
    """
    messages: list[AllMessageValues] = [
        {"role": "system", "content": "You are a performance engineering assistant that produces git patches. Use the read_file tool to examine code when needed, then produce a SUMMARY and PATCH."},
        {"role": "user", "content": prompt},
    ]

    tool_definition = create_read_file_tool()

    last_error = "unknown error"

    for attempt in range(1, Config.MAX_PATCH_ATTEMPTS + 1):
        llm_result, final_messages = call_llm(messages, config, tools=[tool_definition], repo=repo)
        _write_artifact(f"llm_result_attempt{attempt}.txt", llm_result)

        try:
            summary, patch = extract_patch(llm_result)
        except AnalyzerError as exc:
            last_error = exc.message
            print(f"[1g] Attempt {attempt}/{Config.MAX_PATCH_ATTEMPTS}: {last_error}")
        else:
            check_error = _git_apply_check(patch)
            if check_error is None:
                print(f"[1g] Attempt {attempt}/{Config.MAX_PATCH_ATTEMPTS}: patch applies cleanly.")
                return summary, patch, llm_result
            last_error = f"`git apply --check` failed:\n{check_error}"
            print(f"[1g] Attempt {attempt}/{Config.MAX_PATCH_ATTEMPTS}: {last_error}")

        if attempt < Config.MAX_PATCH_ATTEMPTS:
            # call_llm mutates the messages list in place and returns the same
            # object, so `final_messages` is `messages` — no copy needed.
            # Before the retry, replace bulky tool-result messages from the
            # previous attempt with a short placeholder so attempt 2 doesn't
            # re-send the entire file contents the model already summarized.
            for msg in messages:
                if msg.get("role") == "tool":
                    msg["content"] = (
                        "[previous read_file result elided; call read_file again if you need it]"
                    )
            messages.append({
                "role": "user",
                "content": (
                    "Your previous response could not be turned into an applied git patch:\n\n"
                    f"{last_error}\n\n"
                    "Reply again in the exact same SUMMARY/PATCH format described earlier, "
                    "fixing the issue. Use the read_file tool again if needed to verify line numbers."
                ),
            })


    raise AnalyzerError(
        "1h",
        f"No valid patch produced after {Config.MAX_PATCH_ATTEMPTS} attempt(s). Last error: {last_error}",
    )


# ---------------------------------------------------------------------------
# Step 1h — Apply git patch
# ---------------------------------------------------------------------------

def apply_patch(repo: git.Repo, patch: str) -> None:
    """Apply the unified-diff patch via `git apply`."""
    _ensure_artifacts_dir()
    patch_file = Config.ARTIFACTS_DIR / "patch.diff"
    patch_file.write_text(patch + "\n", encoding="utf-8")

    print(f"[1h] Applying patch from {patch_file}")
    _run_command(
        ["git", "apply", "--whitespace=fix", str(patch_file)],
        "1h",
        timeout=Config.GIT_OPERATIONS_TIMEOUT_SECONDS,
        error_prefix="git apply",
    )


# ---------------------------------------------------------------------------
# Step 1j — Create branch, commit, push, open PR
# ---------------------------------------------------------------------------

def _resolve_default_branch(step: str) -> str:
    """Resolve the repository's default branch via `gh repo view`."""
    branch = _run_command(
        ["gh", "repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"],
        step,
        timeout=Config.GH_CLI_TIMEOUT_SECONDS,
        error_prefix="gh repo view",
    ).strip()
    if not branch:
        raise AnalyzerError(step, "Could not resolve repository default branch via `gh repo view`.")
    return branch


def create_pull_request(repo: git.Repo, run_id: str, summary: str, config: EnvConfig) -> tuple[str, str]:
    """Create a branch, commit the applied changes, push, and open a PR via gh."""
    branch_name = f"pprof/fix-{run_id}"
    base_branch = config.base_branch or _resolve_default_branch("1j")
    print(f"[1j] PR base branch: {base_branch}")

    # Create and checkout the new branch.
    print(f"[1j] Creating branch {branch_name}")
    repo.git.checkout("-b", branch_name)

    # Stage all changes except the artifacts directory (generated files for upload, not for commit).
    repo.git.add(A=True)
    repo.git.reset("artifacts")

    # Check if there is anything to commit (patch may have been empty).
    diff = repo.git.diff("--cached")
    if not diff.strip():
        raise AnalyzerError("1j", "No changes to commit after applying the patch.")

    commit_msg = f"pprof-analyzer: fix for run {run_id}\n\n{summary}"
    repo.index.commit(commit_msg)

    # Push the branch.
    token = config.token
    repo_url = repo.remote("origin").url
    # Inject token for push auth.
    authed_url = re.sub(r"(https://)([^@]+@)?", rf"\1x-access-token:{token}@", repo_url)
    print(f"[1j] Pushing {branch_name}")
    try:
        _run_command(
            ["git", "push", authed_url, f"{branch_name}:{branch_name}"],
            "1j",
            timeout=Config.GIT_OPERATIONS_TIMEOUT_SECONDS,
            error_prefix="git push",
        )
    except AnalyzerError as exc:
        # Redact the token from error message to avoid leaking into logs/annotations.
        safe_msg = exc.message.replace(token, "***")
        raise AnalyzerError("1j", safe_msg) from exc

    # Create the PR via gh CLI.
    pr_body = f"""## pprof-analyzer automated fix

**Run ID:** `{run_id}`

{summary}
"""
    print(f"[1j] Creating PR {branch_name} -> {base_branch}")
    pr_url = _run_command(
        [
            "gh", "pr", "create",
            "--base", base_branch,
            "--head", branch_name,
            "--title", f"pprof-analyzer: fix for run {run_id}",
            "--body", pr_body,
        ],
        "1j",
        timeout=Config.GH_CLI_TIMEOUT_SECONDS,
        error_prefix="gh pr create",
    ).strip()

    # Extract PR number from the URL.
    pr_number = pr_url.rstrip("/").split("/")[-1]
    print(f"[1j] PR created: {pr_url} (#{pr_number})")
    return pr_url, pr_number


# ---------------------------------------------------------------------------
# Step 1k — Flag execution as submitted
# ---------------------------------------------------------------------------

def flag_submitted(run_id: str, pr_url: str, pr_number: str, config: EnvConfig) -> None:
    """POST /runs/{run_id}/submit to flag the execution as done/submitted."""
    payload = {
        "pr_url": pr_url,
        "pr_number": pr_number,
    }
    _service_request("POST", f"/runs/{run_id}/submit", "1k", config.service_url, config.ai_key, payload)
    print(f"[1k] Run {run_id} flagged as submitted.")


# ---------------------------------------------------------------------------
# Step 2a — Flag execution as error
# ---------------------------------------------------------------------------

def flag_error(run_id: str, step: str, message: str, config: EnvConfig) -> None:
    """POST /runs/{run_id}/error to flag the execution as error."""
    payload = {
        "step": step,
        "error": message,
    }
    try:
        _service_request("POST", f"/runs/{run_id}/error", "2a", config.service_url, config.ai_key, payload)
        print(f"[2a] Run {run_id} flagged as error (step {step}).")
    except Exception as exc:  # noqa: BLE001
        print(f"[2a] WARNING: failed to flag error for run {run_id}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _fail(
    step: str,
    message: str,
    run_id: str | None,
    config: EnvConfig,
    file_mode: bool,
) -> int:
    """Handle a fatal error: annotate, record, summarize, flag, and return exit code.

    Consolidates the three near-identical failure blocks in main() —
    _gh_annotation → _record_step → _write_step_summary → print → flag_error.
    """
    _gh_annotation("error", message, step)
    _record_step(step, "error")
    _write_step_summary(run_id or "unknown")
    print(f"ERROR during step {step}: {message}", file=sys.stderr)
    if not file_mode and run_id is not None:
        try:
            flag_error(run_id, step, message, config)
        except Exception as e:  # noqa: BLE001
            print(f"[2a] WARNING: failed to flag error: {e}", file=sys.stderr)
    return 1


def main() -> int:

    # --- Load and validate configuration -----------------------------------
    try:
        config = EnvConfig()
    except AnalyzerError as exc:
        _gh_annotation("error", exc.message, exc.step)
        print(f"ERROR during initialization: {exc.message}", file=sys.stderr)
        return 2

    # Pre-flight check: verify the AI endpoint is reachable before doing
    # any expensive work.
    try:

        validate_llm_endpoint(config)
        _record_step("0", "ok")
    except AnalyzerError as exc:
        _gh_annotation("error", exc.message, exc.step)
        _record_step("0", "error")
        _write_step_summary("unknown")
        print(f"ERROR during pre-flight check: {exc.message}", file=sys.stderr)
        return 1

    prompt_template = config.action_path / "prompts" / "prompt_template.txt"

    # File-based (testing) mode: when ANALYZER_RESULT_FILE is set, load a

    # raw pprof profile from a local file and skip all SERVICE_URL
    # interactions (steps 1a trigger, 1b poll, 1k submit, and 2a error-flag).
    file_mode = bool(config.analyzer_result_file)

    run_id = None

    # --- Step 1a: trigger (skipped in file mode) ----------------------------
    if file_mode:
        run_id = local_run_id()
        _set_output("run_id", run_id)
        print(f"[1a] File mode: skipping SERVICE_URL trigger. Using local run_id={run_id}")
    else:
        try:
            run_id = trigger_analyzer(config.reference, config.tags, config.repository, config)
            _set_output("run_id", run_id)
        except AnalyzerError as exc:
            # 1a is outside the 1b-1j error-flag window; just fail.
            return _fail(exc.step, exc.message, run_id, config, file_mode)
        except Exception as exc:  # noqa: BLE001
            return _fail("1a", str(exc), run_id, config, file_mode)

    _record_step("1a", "ok")

    # run_id is non-None on every path that reaches here (file mode sets it
    # via local_run_id; service mode sets it via trigger_analyzer or already
    # returned). Narrow for Pylance so poll_analyzer_result(run_id, ...) type-checks.
    assert run_id is not None

    # --- Steps 1b-1j (wrapped for error flagging) ---------------------------
    try:
        # 1b — obtain raw pprof profile (poll SERVICE_URL, or load from file)
        # Use a truthy check (not `is not None`) so that an empty string is
        # treated the same as None — matching the `bool()` used for file_mode.
        if config.analyzer_result_file:
            pprof_path = load_analyzer_result_from_file(config.analyzer_result_file)
        else:
            pprof_path = poll_analyzer_result(run_id, config)




        # Convert the raw pprof profile to LLM-friendly markdown via pprof-to-md.
        # convert_pprof_to_markdown writes directly to artifacts/analyzer_result.md via -o.
        analyzer_result = convert_pprof_to_markdown(pprof_path, config.action_path)
        _record_step("1b", "ok")



        # 1c — prepare git checkout
        repo = prepare_git_checkout(config.tags)
        _record_step("1c", "ok")

        # 1d — skip repomix; we'll use agent loop file access instead
        print("[1d] Skipping repomix; using agent loop with on-demand file access.")
        _record_step("1d", "ok")

        # 1e — construct prompt with file list

        file_list = list_repo_files(repo)
        prompt = construct_prompt(prompt_template, config.reference, analyzer_result, file_list)

        _write_artifact("prompt.txt", prompt)
        _record_step("1e", "ok")

        # 1f/1g — feed to LLM with tool-use enabled for file access, extract patch
        summary, patch, llm_result = generate_valid_patch(prompt, config, repo=repo)
        _write_artifact("llm_result.txt", llm_result)
        _write_artifact("patch.diff", patch + "\n")
        _record_step("1f", "ok")
        _record_step("1g", "ok")

        # 1h — apply patch (already verified via `git apply --check` above)
        apply_patch(repo, patch)
        _record_step("1h", "ok")

        # 1j — create PR
        pr_url, pr_number = create_pull_request(repo, run_id, summary, config)
        _set_output("pr_url", pr_url)
        _set_output("pr_number", pr_number)
        _record_step("1j", "ok")
        _gh_annotation("notice", f"PR created: {pr_url} (#{pr_number})", "1j")

    except AnalyzerError as exc:
        return _fail(exc.step, exc.message, run_id, config, file_mode)
    except Exception as exc:  # noqa: BLE001
        return _fail("unknown", str(exc), run_id, config, file_mode)


    # --- Step 1k: flag submitted (skipped in file mode) --------------------
    if file_mode:
        print("[1k] File mode: skipping SERVICE_URL submit flag.")
    else:
        try:
            flag_submitted(run_id, pr_url, pr_number, config)
            _record_step("1k", "ok")
        except Exception as exc:  # noqa: BLE001
            # PR was created; failure to flag is non-fatal but should be visible.
            _gh_annotation("warning", f"Failed to flag run {run_id} as submitted: {exc}", "1k")
            _record_step("1k", "error")
            print(f"WARNING: failed to flag run {run_id} as submitted: {exc}", file=sys.stderr)

    _write_step_summary(run_id)
    print("pprof-analyzer completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
