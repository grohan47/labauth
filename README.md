# LabAuth

Local NiceGUI application for the LabAuth display and enrollment workflows.

## Run

```bash
uv sync
uv run python src/main.py
```

Open <http://127.0.0.1:8080/display> in Chromium.

The display loads version-pinned `@sbb-esta/lyne-elements` and
`@sbb-esta/lyne-design-tokens` npm packages at runtime through jsDelivr. No Lyne
packages or transitive frontend dependencies are stored in this repository. An
internet connection is required when loading the UI.
