---
name: kaggle-experiment
description: Run ML experiments on Kaggle Kernels by editing a local repo, pushing to Git, and pulling outputs back. Uses Kaggle CLI and optional shell scripts; long waits and status polling happen outside the Hermes chat loop.
version: 1.0.0
author: community
license: MIT
metadata:
  hermes:
    tags: [Kaggle, ML, GPU, Git, CLI, experiments]
    commands: [git, kaggle]
---

# Kaggle experiment loop (local code → Git → Kernel → results)

Use this skill when the user wants to **iterate on experiment code locally**, **push to a linked GitHub/Git remote**, run logic on **Kaggle** (notebook/kernel clones that repo), then **download logs or metrics** and adjust code in a follow-up turn.

## Prerequisites

1. **Kaggle CLI** installed and authenticated (`kaggle --version`; credentials in `~/.kaggle/kaggle.json` or env vars supported by the official CLI).
2. **Git** remote configured for the experiment repository (SSH or HTTPS with a working credential helper).
3. A **Kaggle Notebook / Kernel** that clones the same repo (branch or commit SHA documented in your project) and writes artifacts under `/kaggle/working/` (or paths you document below).

## Hermes integration

- Prefer `**read_file` / `patch`** for code changes in the experiment repo.
- Prefer `**terminal`** to run **small, fixed entrypoint scripts** (e.g. `bash scripts/kaggle/push_and_trigger.sh`) instead of long one-off shell pipelines. That reduces mistakes and dangerous-command prompts.
- Use `**skills_list` / `skill_view`** if you need only a fragment of this doc; the full file is the source of truth.
- Downloaded experiment outputs and poller artifacts should land under paths you document (e.g. `experiments/runs/<id>/` and optionally `run_log/<experiment_name>/kaggle_output/`), never mixed with Hermes session transcripts under `HERMES_HOME/sessions/`.

## Recommended repository layout (in the experiment repo, not under Hermes)

```text
scripts/kaggle/
  push_and_trigger.sh           # git add/commit/push + optional kaggle kernels push
  fetch_outputs.sh              # kaggle kernels output … → experiments/runs/<id>/
  poll_kernel_and_continue.sh   # optional: copy from skill templates (see below)
  next_turn_prompt.txt          # optional: multiline prompt for Hermes after run completes
experiments/runs/<run_id>/      # poller + kaggle output + summary (gitignore if sensitive)
```

**Bundled templates (copy into your repo):** authoritative copies live under  
`skills/mlops/kaggle/kaggle-experiment/templates/scripts/kaggle/`  
— copy `poll_kernel_and_continue.sh` (and optionally `next_turn_prompt.example.txt` as `next_turn_prompt.txt`) into your experiment repo’s `scripts/kaggle/`, then `chmod +x` the `.sh` file and set `KAGGLE_KERNEL_REF` / `HERMES_NEXT_PROMPT_FILE` as documented in the script header.

The same script also exists under this skill’s `scripts/` directory for in-repo maintenance; **treat `templates/scripts/kaggle/` as the source you copy into user projects** so paths stay predictable.

Adjust paths to match the user’s project; document the exact commands in `references/` if needed.

## Workflow

### Phase A — read logs and make plan

1. Confirm **cwd** is the experiment repository root (or `cd` there in `terminal` once).
2. **Ingest prior runs:** `read_file` anything already on disk that explains the last Kernel outcome—e.g. `experiments/runs/<run_id>/` (`summary.txt`, `status_final.txt`, `poller.log`, `output/`), paths under `run_log/<experiment_name>/kaggle_output/` if you use that layout, and any user-provided changelog.
3. **Summarize** what failed or improved (metrics, errors, missing outputs) in short bullets the user can skim.
4. **Plan** the next iteration: which files to touch, what hypothesis changed, and whether another Kernel run is needed; do **not** start a long poll inside this chat turn.
you can search in the user's repository to find some reference paper to help you make plan.

### Phase B — edit codes, push to github and start kaggle kernel

1. Execute the plan with `**patch`** / `write_file` (and `read_file` for context) in the experiment repo.
2. Run the agreed **push script** (or minimal `git add/commit/push` + `kaggle kernels push` / metadata update) so GitHub matches what the Notebook clones.
3. **Trigger** the Kernel (push, version bump, or whatever your project uses) and capture stdout/stderr for the transcript.
4. Record the **commit SHA** or branch the Kernel should clone; append a one-line note to the project changelog or `experiments/runs/<run_id>/notes.md` if the user wants an audit trail of what changed before this run.
5. Treat this phase as **“fire and start”**: once the run is in flight, hand off monitoring to Phase C—do not block on GPU completion here.

### Phase C — write a script to monitor kaggle and stop this session

1. **Automation first:** add or refine a host-side loop—start from `templates/scripts/kaggle/poll_kernel_and_continue.sh` (or the skill’s `scripts/poll_kernel_and_continue.sh` as reference), install it under `scripts/kaggle/` in the user repo, set `KAGGLE_KERNEL_REF` and prompt env vars, then run with `nohup` or cron so `kaggle kernels status` polls until success, failure, or timeout.
2. Have that script write compact artifacts for the **next** Hermes turn under `experiments/runs/<run_id>/` (`summary.txt`, `status_final.txt`, logs) or under your agreed `run_log/` tree so Phase A can open cold.
3. If you use `HERMES_NEXT_PROMPT_FILE` / `next_turn_prompt.txt`, keep the template in sync with the repo file and document the path in the script header so the follow-up `hermes chat -q` receives the right instructions.
4. **End this session cleanly:** tell the user the watcher is running and they should close or background the chat; long GPU waits belong outside the live agent loop, not in an idle Hermes conversation.

## Safety and hygiene

- **Never** paste Kaggle tokens or Git HTTPS passwords into chat or commit them into tracked files. Use **Kaggle Secrets** inside the notebook for private repo tokens.
- Avoid `**git push --force`** unless the user explicitly requests it and understands the risk.
- Keep **Kernel slug / owner / dataset names** in project docs or env, not duplicated with typos across many commands.
- Before relying on `HERMES_NEXT_PROMPT_FILE`, re-read the file you will pass to `hermes chat -q` so secrets, wrong paths, or stale OWNER/SLUG placeholders are not sent blindly.

## Failure handling


| Symptom                  | Suggested action                                                                                   |
| ------------------------ | -------------------------------------------------------------------------------------------------- |
| `kaggle` auth error      | Ask user to verify `~/.kaggle/kaggle.json` or env; do not guess credentials.                       |
| Push rejected            | Show remote message; suggest `git pull --rebase` only if the user wants branch convergence.        |
| Kernel failed            | `read_file` downloaded stderr/log; fix code or config; re-run push/trigger.                        |
| Empty or missing outputs | Confirm Kernel writes to `/kaggle/working/` and fetch script targets the correct slug/output path. |


## Optional references

Add files under `references/` in this skill directory (e.g. `references/kernel-metadata.md`) for **project-specific** Kernel slugs, accelerator types, and exact `kaggle` subcommands. Load with:

`skill_view("mlops/kaggle/kaggle-experiment", "references/kernel-metadata.md")`

(Adjust the first argument if your installed skill path differs.)
(please ask user the message that you think you need to do this task)
