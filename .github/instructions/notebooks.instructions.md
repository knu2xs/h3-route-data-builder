---
applyTo: "**/*.ipynb,notebooks/**"
---

<!-- Generated from AGENTS.md by post_gen_project.py — do not edit directly. -->

Notebooks under `notebooks/` are for exploratory work. Apply these rules to keep them
reviewable and free of stale artifacts:

- **Strip outputs before committing.** Install [`nbstripout`](https://github.com/kynan/nbstripout)
  as a Git filter (`nbstripout --install`) so committed `.ipynb` files contain no cell outputs,
  execution counts, or metadata churn. Outputs bloat diffs and may leak data or credentials.
- **Restart-and-run-all** before committing. A notebook that does not run top-to-bottom in a
  fresh kernel is broken; do not commit it.
- **No secrets in notebooks.** Use `secrets.*` from `h3_route_data_builder.config`
  rather than pasting tokens, profile names, or URLs into cells.
- **Promote reusable code out of notebooks.** Once a function works, move it into
  `src/h3_route_data_builder/` and import it back into the notebook. Notebooks
  should orchestrate, not own logic.
- **Notebooks intended for documentation** belong under `docsrc/mkdocs/notebooks/` and are
  rendered by `mkdocs-jupyter`; keep their outputs (since they are the documentation) but
  still restart-and-run-all before committing.
- **Prefer JupyterLab via `make jupyter`** so the kernel matches the project conda env.
