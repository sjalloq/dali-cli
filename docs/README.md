# DALI Controller API Docs

This is a Sphinx documentation site for your DALI network controller’s REST API.
It is set up to render an OpenAPI/Swagger spec directly in the docs.

## Prerequisites
- Python 3.9+
- `pip`

## Setup
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r docs/requirements.txt
```

## Fetch the OpenAPI spec from your controller
Most controllers expose the schema at `/openapi.json` (FastAPI/Swagger UI) or `/swagger.json`.
Try the following and place the file as shown:
```bash
curl -fsS http://10.0.0.239/openapi.json -o docs/source/openapi/openapi.json || \
curl -fsS http://10.0.0.239/swagger.json -o docs/source/openapi/openapi.json
```

If your controller hosts only the interactive UI at `/docs`, open it in a browser and download the JSON from the Swagger UI (often a “Raw” or “Download” button).

## Build the docs
```bash
make -C docs html
open docs/build/html/index.html
```

If you change the OpenAPI file, rebuild to see updates.

## Troubleshooting
- If the build complains about `sphinxcontrib.openapi` not found, ensure dependencies are installed:
  ```bash
  pip install -r docs/requirements.txt
  ```
- If the OpenAPI is at a different URL, fetch it and save as `docs/source/openapi/openapi.json`.
- If your spec is YAML, save it as `docs/source/openapi/openapi.yaml` and update `api/index.rst` accordingly.

