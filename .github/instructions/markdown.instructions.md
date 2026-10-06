---
applyTo: "**/*.md"
---

<!-- Generated from AGENTS.md by post_gen_project.py — do not edit directly. -->

### 3. Markdown Conventions

- **Headings**: Use ATX-style headers (`#`, `##`, `###`, etc.)
- **Lists**:
    - Use hyphens (`-`) for unordered lists
    - Use numbers for ordered lists
    - Ensure there is a line preceding lists so they are formatted correctly for MkDocs
- **Emphasis**: Use `*italic*` for emphasis and `**bold**` for strong emphasis
- **Indentation**: Use four spaces for indentation/tabs (not tab characters)
- **Code**:
    - Use single backticks for inline code: `` `variable_name` ``
    - Use triple backticks with language identifiers for code blocks
    - When including code in docstrings, use triple backticks with the language identifier 
      (e.g., `` ```python ``)
- **Links**: Use descriptive link text: `[link text](URL)`
- **Admonitions**: Use MkDocs-style admonitions in documentation and docstrings:
    - `!!! note` for general information
    - `!!! warning` for important warnings
    - `!!! tip` for helpful tips
    - `!!! danger` for critical warnings
    - `!!! example` for examples
    - **Collapsible Admonitions**: Use `???` instead of `!!!` to make admonitions collapsible by default
    - Use `???+` to make collapsible admonitions expanded by default
- **Tables**: Use pipe-delimited tables with header separators (`|---|---|`)
- **Line Length**: Keep markdown lines under 120 characters when possible for readability
- Follow style guidance and conventions from the
  [MkDocs Material documentation](https://squidfunk.github.io/mkdocs-material/) as the primary
  reference. For anything not covered there, fall back to the
  [MkDocs documentation](https://www.mkdocs.org/user-guide/writing-your-docs/).
