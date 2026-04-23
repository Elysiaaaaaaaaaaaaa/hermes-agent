# Kernel metadata (fill in for your project)

Copy this file’s ideas into your **experiment** repo if you prefer not to edit the bundled skill.

| Field | Example | Notes |
|--------|---------|--------|
| Kernel user | `your_kaggle_username` | Owner slug in URLs |
| Kernel slug | `my-exp-notebook` | As shown on Kaggle |
| Git remote | `https://github.com/org/repo.git` | What the notebook `git clone`s |
| Default branch / pin | `main` or commit SHA | Reproducibility |

## Example commands (verify against current Kaggle CLI docs)

```bash
# After local git push — if you use kernel push from CLI:
# kaggle kernels push -p /path/to/kernel/dir

# Download outputs from a completed run (flags vary by CLI version):
# kaggle kernels output <user>/<slug> -p experiments/runs/<run_id>/
```

Replace placeholders before relying on automation.
