#!/usr/bin/env python3
"""
pprof-analyzer orchestration script.

Implements the flow described in the action spec:
  1a  Trigger analyzer execution via SERVICE_URL.
  1b  Poll SERVICE_URL for the analyzer result.
  1c  Verify / prepare the git checkout branch.
  1d  Run `repomix` to produce an LLM-compatible XML of the repo.
  1e  Construct the prompt.
  1f  Feed the prompt to the LLM.
  1g  Extract the git patch from the LLM result.
  1h  Apply the git patch.
  1i  (Artifacts are written to ./artifacts; the composite action uploads them.)
  1j  Commit, push, and create a Pull Request.
  1k  Flag the execution as submitted via SERVICE_URL.

If any step 1b-1j fails, step 2a flags the execution as error via SERVICE_URL.
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
import time
from pathlib import Path



import git
import requests
from openai import OpenAI

# ---------------------------------------------------------------------------
# Configuration & Constants
# ---------------------------------------------------------------------------

class Config:
    """Centralized configuration constants."""
    REQUEST_TIMEOUT_SECONDS = 60
    POLL_INTERVAL_SECONDS = 15
    POLL_TIMEOUT_SECONDS = 10 * 60
    PPROF_TO_MD_TIMEOUT_SECONDS = 60
    REPOMIX_TIMEOUT_SECONDS = 120
    GIT_OPERATIONS_TIMEOUT_SECONDS = 120
    GH_CLI_TIMEOUT_SECONDS = 180

    ARTIFACTS_DIR = Path("artifacts")
    REPOMIX_OUTPUT_DIR = Path("repomix-output")

    VALID_REFERENCES = {"low", "med", "high"}

    PATCH_FENCE_PATTERN = r"```(?:diff[a-z-]*)?\n(.*?)```"
    SUMMARY_PATTERN = r"###\s*SUMMARY\s*\n(.*?)(?:###\s*PATCH|\Z)"

    STEP_DESCRIPTIONS: dict[str, str] = {
        "1a": "Trigger analyzer",
        "1b": "Poll analyzer result / convert pprof",
        "1c": "Prepare git checkout",
        "1d": "Run repomix",
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

    try:
        if method.upper() == "GET":
            resp = requests.get(url, headers=headers, timeout=Config.REQUEST_TIMEOUT_SECONDS)
        elif method.upper() == "POST":
            resp = requests.post(
                url, headers=headers, json=payload, timeout=Config.REQUEST_TIMEOUT_SECONDS
            )
        else:
            raise AnalyzerError(step, f"Unsupported HTTP method: {method}")

        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        raise AnalyzerError(step, f"Request to {endpoint} failed: {exc}") from exc


def _run_command(
    cmd: list, step: str, timeout: int = None, error_prefix: str = ""
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

    The composite action runs ``npm ci`` in ``${ACTION_PATH}`` (see action.yml),
    which installs ``repomix`` and ``pprof-to-md`` into
    ``${ACTION_PATH}/node_modules/.bin``. This helper returns the absolute path
    to the requested binary so the analyzer can invoke the exact pinned version
    regardless of the current working directory or global PATH.

    Using the local binary (instead of ``npx --yes <pkg>``) avoids a network
    re-resolve at runtime and guarantees the version pinned in
    ``package-lock.json`` is the one that runs.
    """
    candidate = action_path / "node_modules" / ".bin" / name
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

        time.sleep(Config.POLL_INTERVAL_SECONDS)

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
# Step 1d — Run repomix
# ---------------------------------------------------------------------------

def run_repomix(action_path: Path) -> str:
    """Run `repomix` to produce an XML representation of the repo.

    Uses the locally-installed (pinned) binary from ``${ACTION_PATH}/node_modules/.bin``
    rather than ``npx --yes repomix``. This avoids a network re-resolve at
    runtime and guarantees the version pinned in ``package-lock.json`` runs.
    """
    Config.REPOMIX_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = Config.REPOMIX_OUTPUT_DIR / "repomix.xml"

    cmd = [
        _node_bin("repomix", action_path),
        "--style", "xml",
        "--token-count-tree",  "--output-show-line-numbers", 
        "--output", str(out_file),
    ]
    print(f"[1d] Running: {' '.join(cmd)}")
    _run_command(cmd, "1d", timeout=Config.REPOMIX_TIMEOUT_SECONDS, error_prefix="repomix")

    if not out_file.exists():
        raise AnalyzerError("1d", f"repomix output not found at {out_file}")

    content = out_file.read_text(encoding="utf-8")
    print(f"[1d] repomix produced {len(content)} chars.")
    return content


# ---------------------------------------------------------------------------
# Step 1e — Construct prompt
# ---------------------------------------------------------------------------

def construct_prompt(template_path: Path, reference: str, analyzer_result: str, repomix: str) -> str:
    template = template_path.read_text(encoding="utf-8")
    prompt = template.format(
        reference_level=reference,
        analyzer_result=analyzer_result,
        repomix_result=repomix,
    )
    print(f"[1e] Prompt constructed ({len(prompt)} chars).")
    return prompt



# ---------------------------------------------------------------------------
# Step 1f — Feed to LLM
# ---------------------------------------------------------------------------

def call_llm(prompt: str, config: EnvConfig) -> str:
    """Call the OpenAI-compatible endpoint and return the raw text response."""
    client = OpenAI(
        api_key=config.ai_key,
        base_url=config.ai_endpoint,
        timeout=300,
    )
    print(f"[1f] Calling LLM (model={config.ai_model})...")
    completion = client.chat.completions.create(
        model=config.ai_model,
        messages=[
            {"role": "system", "content": "You are a performance engineering assistant that produces git patches."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    text = completion.choices[0].message.content or ""
    print(f"[1f] LLM returned {len(text)} chars.")
    return text


# ---------------------------------------------------------------------------
# Step 1g — Extract git patch from LLM result
# ---------------------------------------------------------------------------

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
# Step 1h — Apply git patch
# ---------------------------------------------------------------------------

def apply_patch(repo: git.Repo, patch: str) -> None:
    """Apply the unified-diff patch via `git apply`."""
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

    # Stage all changes.
    repo.git.add(A=True)

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

def main() -> int:
    # --- Load and validate configuration -----------------------------------
    try:
        config = EnvConfig()
    except AnalyzerError as exc:
        _gh_annotation("error", exc.message, exc.step)
        print(f"ERROR during initialization: {exc.message}", file=sys.stderr)
        return 2

    prompt_template = config.action_path / "scripts" / "prompts" / "prompt_template.txt"

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
            _gh_annotation("error", exc.message, exc.step)
            _record_step("1a", "error")
            _write_step_summary(run_id or "unknown")
            print(f"ERROR during step 1a: {exc.message}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001
            # Network or other unexpected error
            _gh_annotation("error", str(exc), "1a")
            _record_step("1a", "error")
            _write_step_summary("unknown")
            print(f"ERROR during step 1a: {exc}", file=sys.stderr)
            return 1
    _record_step("1a", "ok")

    # --- Steps 1b-1j (wrapped for error flagging) ---------------------------
    try:
        # 1b — obtain raw pprof profile (poll SERVICE_URL, or load from file)
        if file_mode:
            pprof_path = load_analyzer_result_from_file(config.analyzer_result_file)
        else:
            pprof_path = poll_analyzer_result(run_id, config)

        # Convert the raw pprof profile to LLM-friendly markdown via
        # pprof-to-md. The markdown replaces the old JSON analyzer result.
        # convert_pprof_to_markdown writes directly to artifacts/analyzer_result.md
        # via -o; the explicit _write_artifact below guarantees the artifact
        # exists at the expected path (consistent with all other steps).
        analyzer_result = convert_pprof_to_markdown(pprof_path, config.action_path)
        _write_artifact("analyzer_result.md", analyzer_result)
        _record_step("1b", "ok")

        # 1c — prepare git checkout
        repo = prepare_git_checkout(config.tags)
        _record_step("1c", "ok")

        # 1d — run repomix
        repomix = run_repomix(config.action_path)
        _write_artifact("repomix_result.xml", repomix)
        _record_step("1d", "ok")

        # 1e — construct prompt
        prompt = construct_prompt(prompt_template, config.reference, analyzer_result, repomix)
        _write_artifact("prompt.txt", prompt)
        _record_step("1e", "ok")

        # 1f — feed to LLM
        llm_result = call_llm(prompt, config)
        _write_artifact("llm_result.txt", llm_result)
        _record_step("1f", "ok")

        # 1g — extract patch
        summary, patch = extract_patch(llm_result)
        _write_artifact("patch.diff", patch + "\n")
        _record_step("1g", "ok")

        # 1h — apply patch
        apply_patch(repo, patch)
        _record_step("1h", "ok")

        # 1j — create PR
        pr_url, pr_number = create_pull_request(repo, run_id, summary, config)
        _set_output("pr_url", pr_url)
        _set_output("pr_number", pr_number)
        _record_step("1j", "ok")
        _gh_annotation("notice", f"PR created: {pr_url} (#{pr_number})", "1j")

    except AnalyzerError as exc:
        _gh_annotation("error", exc.message, exc.step)
        _record_step(exc.step, "error")
        _write_step_summary(run_id or "unknown")
        print(f"ERROR during step {exc.step}: {exc.message}", file=sys.stderr)
        # 2a — flag error (skipped in file mode; no SERVICE_URL run registered)
        if not file_mode:
            try:
                flag_error(run_id, exc.step, exc.message, config)
            except Exception as e:  # noqa: BLE001
                print(f"[2a] WARNING: failed to flag error: {e}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        _gh_annotation("error", str(exc), "unknown")
        _write_step_summary(run_id or "unknown")
        print(f"ERROR during steps 1b-1j: {exc}", file=sys.stderr)
        if not file_mode:
            try:
                flag_error(run_id, "unknown", str(exc), config)
            except Exception as e:  # noqa: BLE001
                print(f"[2a] WARNING: failed to flag error: {e}", file=sys.stderr)
        return 1

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
