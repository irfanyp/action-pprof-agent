#!/usr/bin/env python3
"""
pprof-analyzer orchestration script.

Implements the flow described in the action spec:
  1a  Trigger analyzer execution via SERVICE_URL.
  1b  Poll SERVICE_URL for the analyzer result.
  1c  Verify / prepare the git checkout branch.
  1d  Run `npx repomix` to produce an LLM-compatible XML of the repo.
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

import json
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
# Configuration
# ---------------------------------------------------------------------------

# SERVICE_URL is hardcoded in the action (per spec).
SERVICE_URL = "https://analyzer.internal/api/v1"

# Base URL of the GitHub instance running the workflow.
# On public GitHub this is "https://github.com"; on GitHub Enterprise Server
# it is the instance URL (e.g. "https://github.example.com").
# Provided by the runner via the `github.server_url` context.
GITHUB_SERVER_URL = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")


# Polling configuration for step 1b.
POLL_INTERVAL_SECONDS = 15
POLL_TIMEOUT_SECONDS = 10 * 60  # 10 minutes

# Valid reference levels.
VALID_REFERENCES = {"low", "med", "high"}

# Directory where artifacts are written (step 1i).
ARTIFACTS_DIR = Path("artifacts")

# Directory for temporary repomix output.
REPOMIX_OUTPUT_DIR = Path("repomix-output")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class AnalyzerError(Exception):
    """Raised when a step in the 1b-1j flow fails. Carries the step label."""

    def __init__(self, step: str, message: str):
        self.step = step
        self.message = message
        super().__init__(f"[{step}] {message}")


def _auth_headers() -> dict:
    """Authorization headers for SERVICE_URL (bearer token = AI_KEY)."""
    return {
        "Authorization": f"Bearer {os.environ['AI_KEY']}",
        "Content-Type": "application/json",
    }


def _ensure_artifacts_dir() -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def _write_artifact(name: str, content: str) -> Path:
    _ensure_artifacts_dir()
    path = ARTIFACTS_DIR / name
    path.write_text(content, encoding="utf-8")
    return path


def _set_output(name: str, value: str) -> None:
    """Set a GitHub Actions step output."""
    # $GITHUB_OUTPUT is provided by the runner.
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


# ---------------------------------------------------------------------------
# Step 1a — Trigger analyzer execution
# ---------------------------------------------------------------------------

def trigger_analyzer(reference: str, tags: str, repository: str) -> str:
    """POST /runs to authenticate and trigger the analyzer. Returns run_id."""
    payload = {
        "reference": reference,
        "tags": tags,
        "repository": repository,
    }
    resp = requests.post(
        f"{SERVICE_URL}/runs",
        headers=_auth_headers(),
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    run_id = data.get("run_id")
    if not run_id:
        raise AnalyzerError("1a", f"No run_id in trigger response: {data}")
    print(f"[1a] Analyzer triggered. run_id={run_id}")
    return run_id


# ---------------------------------------------------------------------------
# Step 1b — Poll for analyzer result
# ---------------------------------------------------------------------------

def poll_analyzer_result(run_id: str) -> dict:
    """GET /runs/{run_id} periodically until status == completed."""
    url = f"{SERVICE_URL}/runs/{run_id}"
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    last_status = None

    while time.time() < deadline:
        resp = requests.get(url, headers=_auth_headers(), timeout=60)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status", "unknown")
        if status != last_status:
            print(f"[1b] Polling run {run_id}: status={status}")
            last_status = status

        if status == "completed":
            result = data.get("result", {})
            print(f"[1b] Analyzer completed.")
            return result
        if status == "error":
            raise AnalyzerError("1b", f"Analyzer reported error: {data}")

        time.sleep(POLL_INTERVAL_SECONDS)

    raise AnalyzerError("1b", f"Timed out after {POLL_TIMEOUT_SECONDS}s waiting for run {run_id}")


# ---------------------------------------------------------------------------
# Step 1b (file mode) — Load analyzer result from a local JSON file
# ---------------------------------------------------------------------------

def load_analyzer_result_from_file(path_str: str) -> dict:
    """Load a pre-computed analyzer result from a JSON file (testing mode).

    Replaces steps 1a (trigger) and 1b (poll) when ANALYZER_RESULT_FILE is set.
    """
    path = Path(path_str)
    if not path.is_file():
        raise AnalyzerError("1b", f"Analyzer result file not found: {path}")
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AnalyzerError("1b", f"Failed to parse analyzer result file as JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise AnalyzerError("1b", f"Analyzer result file must contain a JSON object, got {type(result).__name__}")
    print(f"[1b] Loaded analyzer result from {path} ({len(result)} top-level keys).")
    return result


def local_run_id() -> str:
    """Generate a deterministic run_id for file-based (testing) runs."""
    return f"local-{int(time.time())}"


# ---------------------------------------------------------------------------
# Step 1c — Verify / prepare git checkout
# ---------------------------------------------------------------------------


def prepare_git_checkout(tags: str) -> git.Repo:
    """Ensure we are on the requested branch and the repo is usable."""
    try:
        repo = git.Repo(os.getcwd())
    except git.InvalidGitRepositoryError as exc:
        raise AnalyzerError("1c", f"Not a git repository: {exc}") from exc

    current = repo.active_branch.name if not repo.head.is_detached else repo.head.commit.hexsha
    print(f"[1c] Current checkout: {current} (requested: {tags})")
    if current != tags:
        # checkout already happened in the composite action; warn if mismatched.
        print(f"[1c] WARNING: checked-out ref '{current}' differs from requested '{tags}'")
    return repo


# ---------------------------------------------------------------------------
# Step 1d — Run repomix
# ---------------------------------------------------------------------------

def run_repomix() -> str:
    """Run `npx repomix` to produce an XML representation of the repo."""
    REPOMIX_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = REPOMIX_OUTPUT_DIR / "repomix.xml"

    cmd = [
        "npx", "--yes", "repomix",
        "--style", "xml",
        "--output", str(out_file),
    ]
    print(f"[1d] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AnalyzerError("1d", f"repomix failed: {result.stderr}")

    if not out_file.exists():
        raise AnalyzerError("1d", f"repomix output not found at {out_file}")

    content = out_file.read_text(encoding="utf-8")
    print(f"[1d] repomix produced {len(content)} chars.")
    return content


# ---------------------------------------------------------------------------
# Step 1e — Construct prompt
# ---------------------------------------------------------------------------

def construct_prompt(template_path: Path, reference: str, analyzer_result: dict, repomix: str) -> str:
    template = template_path.read_text(encoding="utf-8")
    prompt = template.format(
        reference_level=reference,
        analyzer_result=json.dumps(analyzer_result, indent=2),
        repomix_result=repomix,
    )
    print(f"[1e] Prompt constructed ({len(prompt)} chars).")
    return prompt


# ---------------------------------------------------------------------------
# Step 1f — Feed to LLM
# ---------------------------------------------------------------------------

def call_llm(prompt: str) -> str:
    """Call the OpenAI-compatible endpoint and return the raw text response."""
    client = OpenAI(
        api_key=os.environ["AI_KEY"],
        base_url=os.environ["AI_ENDPOINT"],
    )
    model = os.environ["AI_MODEL"]
    print(f"[1f] Calling LLM (model={model})...")
    completion = client.chat.completions.create(
        model=model,
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
    """
    Extract the SUMMARY section and the diff patch from the LLM result.
    Returns (summary, patch).
    """
    # Extract the diff code fence.
    diff_match = re.search(r"```diff\n(.*?)```", llm_result, re.DOTALL)
    if not diff_match:
        raise AnalyzerError("1g", "No ```diff code fence found in LLM result.")
    patch = diff_match.group(1).strip()

    # Extract the SUMMARY section.
    summary_match = re.search(r"###\s*SUMMARY\s*\n(.*?)(?:###\s*PATCH|\Z)", llm_result, re.DOTALL | re.IGNORECASE)
    summary = summary_match.group(1).strip() if summary_match else "Automated pprof-analyzer fix."

    print(f"[1g] Extracted patch ({len(patch)} chars) and summary ({len(summary)} chars).")
    return summary, patch


# ---------------------------------------------------------------------------
# Step 1h — Apply git patch
# ---------------------------------------------------------------------------

def apply_patch(repo: git.Repo, patch: str) -> None:
    """Apply the unified-diff patch via `git apply`."""
    patch_file = ARTIFACTS_DIR / "patch.diff"
    patch_file.write_text(patch + "\n", encoding="utf-8")
    print(f"[1h] Applying patch from {patch_file}")
    result = subprocess.run(
        ["git", "apply", "--whitespace=fix", str(patch_file)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AnalyzerError("1h", f"git apply failed: {result.stderr}")


# ---------------------------------------------------------------------------
# Step 1j — Create branch, commit, push, open PR
# ---------------------------------------------------------------------------

def create_pull_request(repo: git.Repo, run_id: str, summary: str) -> tuple[str, str]:
    """Create a branch, commit the applied changes, push, and open a PR via gh."""
    branch_name = f"pprof/fix-{run_id}"
    base_branch = repo.active_branch.name if not repo.head.is_detached else os.environ.get("TAGS", "main")

    # Create and checkout the new branch.
    print(f"[1j] Creating branch {branch_name}")
    repo.git.checkout("-b", branch_name)

    # Stage all changes.
    repo.git.add(A=True)

    # Check if there is anything to commit.
    if not repo.is_dirty() and not repo.untracked_files:
        # `git add -A` may have staged nothing if patch was empty.
        diff = repo.git.diff("--cached")
        if not diff.strip():
            raise AnalyzerError("1j", "No changes to commit after applying the patch.")

    commit_msg = f"pprof-analyzer: fix for run {run_id}\n\n{summary}"
    repo.index.commit(commit_msg)

    # Push the branch.
    token = os.environ["GITHUB_TOKEN"]
    repo_url = repo.remote("origin").url
    # Inject token for push auth.
    authed_url = re.sub(r"(https://)([^@]+@)?", rf"\1x-access-token:{token}@", repo_url)
    print(f"[1j] Pushing {branch_name}")
    push_result = subprocess.run(
        ["git", "push", authed_url, f"{branch_name}:{branch_name}"],
        capture_output=True,
        text=True,
    )
    if push_result.returncode != 0:
        raise AnalyzerError("1j", f"git push failed: {push_result.stderr}")

    # Create the PR via gh CLI.
    pr_body = f"""## pprof-analyzer automated fix

**Run ID:** `{run_id}`

{summary}
"""
    print(f"[1j] Creating PR {branch_name} -> {base_branch}")
    gh_result = subprocess.run(
        [
            "gh", "pr", "create",
            "--base", base_branch,
            "--head", branch_name,
            "--title", f"pprof-analyzer: fix for run {run_id}",
            "--body", pr_body,
        ],
        capture_output=True,
        text=True,
        env={**os.environ},
    )
    if gh_result.returncode != 0:
        raise AnalyzerError("1j", f"gh pr create failed: {gh_result.stderr}")

    pr_url = gh_result.stdout.strip()
    # Extract PR number from the URL.
    pr_number = pr_url.rstrip("/").split("/")[-1]
    print(f"[1j] PR created: {pr_url} (#{pr_number})")
    return pr_url, pr_number


# ---------------------------------------------------------------------------
# Step 1k — Flag execution as submitted
# ---------------------------------------------------------------------------

def flag_submitted(run_id: str, pr_url: str, pr_number: str) -> None:
    """POST /runs/{run_id}/submit to flag the execution as done/submitted."""
    payload = {
        "pr_url": pr_url,
        "pr_number": pr_number,
    }
    resp = requests.post(
        f"{SERVICE_URL}/runs/{run_id}/submit",
        headers=_auth_headers(),
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    print(f"[1k] Run {run_id} flagged as submitted.")


# ---------------------------------------------------------------------------
# Step 2a — Flag execution as error
# ---------------------------------------------------------------------------

def flag_error(run_id: str, step: str, message: str) -> None:
    """POST /runs/{run_id}/error to flag the execution as error."""
    payload = {
        "step": step,
        "error": message,
    }
    try:
        resp = requests.post(
            f"{SERVICE_URL}/runs/{run_id}/error",
            headers=_auth_headers(),
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        print(f"[2a] Run {run_id} flagged as error (step {step}).")
    except Exception as exc:  # noqa: BLE001
        print(f"[2a] WARNING: failed to flag error for run {run_id}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # --- Validate inputs ----------------------------------------------------
    reference = os.environ.get("REFERENCE", "").strip().lower()
    if reference not in VALID_REFERENCES:
        print(f"ERROR: 'reference' must be one of {sorted(VALID_REFERENCES)}, got '{reference}'")
        return 2
    tags = os.environ.get("TAGS", "").strip()
    if not tags:
        print("ERROR: 'tags' input is required (checkout branch/tag).")
        return 2
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not repository:
        print("ERROR: GITHUB_REPOSITORY is not set.")
        return 2

    action_path = Path(os.environ["ACTION_PATH"])
    prompt_template = action_path / "scripts" / "prompts" / "prompt_template.txt"

    # File-based (testing) mode: when ANALYZER_RESULT_FILE is set, load the
    # analyzer result from a local JSON file and skip all SERVICE_URL
    # interactions (steps 1a trigger, 1b poll, 1k submit, and 2a error-flag).
    analyzer_result_file = os.environ.get("ANALYZER_RESULT_FILE", "").strip()
    file_mode = bool(analyzer_result_file)

    run_id = None

    # --- Step 1a: trigger (skipped in file mode) ----------------------------
    if file_mode:
        run_id = local_run_id()
        _set_output("run_id", run_id)
        print(f"[1a] File mode: skipping SERVICE_URL trigger. Using local run_id={run_id}")
    else:
        try:
            run_id = trigger_analyzer(reference, tags, repository)
            _set_output("run_id", run_id)
        except Exception as exc:  # noqa: BLE001
            # 1a is outside the 1b-1j error-flag window; just fail.
            print(f"ERROR during step 1a: {exc}", file=sys.stderr)
            return 1

    # --- Steps 1b-1j (wrapped for error flagging) ---------------------------
    try:
        # 1b — obtain analyzer result (poll SERVICE_URL, or load from file)
        if file_mode:
            analyzer_result = load_analyzer_result_from_file(analyzer_result_file)
        else:
            analyzer_result = poll_analyzer_result(run_id)
        _write_artifact("analyzer_result.json", json.dumps(analyzer_result, indent=2))


        # 1c — prepare git checkout
        repo = prepare_git_checkout(tags)

        # 1d — run repomix
        repomix = run_repomix()
        _write_artifact("repomix_result.xml", repomix)

        # 1e — construct prompt
        prompt = construct_prompt(prompt_template, reference, analyzer_result, repomix)

        # 1f — feed to LLM
        llm_result = call_llm(prompt)
        _write_artifact("llm_result.txt", llm_result)

        # 1g — extract patch
        summary, patch = extract_patch(llm_result)
        _write_artifact("patch.diff", patch + "\n")

        # 1h — apply patch
        apply_patch(repo, patch)

        # 1j — create PR
        pr_url, pr_number = create_pull_request(repo, run_id, summary)
        _set_output("pr_url", pr_url)
        _set_output("pr_number", pr_number)

    except AnalyzerError as exc:
        print(f"ERROR during step {exc.step}: {exc.message}", file=sys.stderr)
        # 2a — flag error (skipped in file mode; no SERVICE_URL run registered)
        if not file_mode:
            flag_error(run_id, exc.step, exc.message)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR during steps 1b-1j: {exc}", file=sys.stderr)
        if not file_mode:
            flag_error(run_id, "unknown", str(exc))
        return 1

    # --- Step 1k: flag submitted (skipped in file mode) --------------------
    if file_mode:
        print("[1k] File mode: skipping SERVICE_URL submit flag.")
    else:
        try:
            flag_submitted(run_id, pr_url, pr_number)
        except Exception as exc:  # noqa: BLE001
            # PR was created; failure to flag is non-fatal but should be visible.
            print(f"WARNING: failed to flag run {run_id} as submitted: {exc}", file=sys.stderr)


    print("pprof-analyzer completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
