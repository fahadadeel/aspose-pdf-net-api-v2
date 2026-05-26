# Deployment

## Production (Windows VM)

The app runs as a Windows service managed by [NSSM](https://nssm.cc/).

**Service path**: `C:\fahad\aspose-pdf-net-api-v2`

### Managing the Service

```powershell
# Start / stop / restart
nssm start aspose-pdf-api-v2
nssm stop aspose-pdf-api-v2
nssm restart aspose-pdf-api-v2

# Check status
nssm status aspose-pdf-api-v2

# Edit service config
nssm edit aspose-pdf-api-v2
```

### Environment Config

Production uses `.env.production`. Set `APP_ENV=production` to load it:

```powershell
$env:APP_ENV = "production"
uvicorn main:app --host 0.0.0.0 --port 7103 --workers 1
```

### Updating Production

```powershell
cd C:\fahad\aspose-pdf-net-api-v2
git pull origin main
nssm restart aspose-pdf-api-v2
```

No restart is needed for rule file changes — `resources/generation_rules.json` and `resources/error_fixes.json` are loaded lazily per job.

## Local Development

```bash
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 7103 --workers 1 --reload
```

`--reload` is safe for development but must not be used in production alongside `--workers 1`.

## Parallel Mode

For running multiple categories in parallel, use the orchestrator script:

```bash
# Run all categories with 4 workers
python scripts/parallel_run.py --all --workers 4

# Run specific categories
python scripts/parallel_run.py --categories "annotations,forms" --workers 2

# Retry all failed
python scripts/parallel_run.py --all-failed --workers 4
```

Each worker spawns its own uvicorn instance on ports `7110+` with an isolated workspace.
Git operations are disabled in parallel mode (`repo_push: False`) — create PRs afterwards via the Results Dashboard at `http://localhost:7103/results-v2`.

## GitLab CI

The pipeline runs unit tests on every push to `main` and on merge requests.
See `.gitlab-ci.yml` at the project root.

## GitHub Actions

`.github/workflows/ci.yml` mirrors the GitLab CI pipeline for GitHub-hosted mirrors.
