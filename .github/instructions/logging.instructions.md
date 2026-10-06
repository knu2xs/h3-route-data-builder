---
applyTo: "src/**/*.py,scripts/**/*.py,**/*.pyt"
---

<!-- Generated from AGENTS.md by post_gen_project.py — do not edit directly. -->

#### 12.1 `get_logger`

`get_logger` is a project-defined utility implemented in
`src/h3_route_data_builder/utils/_logging.py` and included by default in generated
projects. It returns a configured `logging.Logger` that routes messages to the console, a logfile,
and/or ArcPy messaging (`arcpy.AddMessage` / `AddWarning` / `AddError`) depending on the options
provided.

#### 12.2 Module-level loggers

Every module in `src/h3_route_data_builder/` should configure a logger at the top of
the file. Use `__name__` as the logger name so log output identifies the originating module:

```python
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level='DEBUG', add_stream_handler=False)
```

- Set `level='DEBUG'` in modules so all messages are captured; the effective output level is
  controlled by the root logger configured in scripts
- Set `add_stream_handler=False` in modules to avoid duplicate console output

#### 12.3 Script-level (root) logger

Scripts in `scripts/` configure the root logger once at the entry point, which applies to all
module-level loggers via propagation:

```python
import datetime
from pathlib import Path
from h3_route_data_builder.utils import get_logger

script_pth = Path(__file__)
dir_logs = script_pth.parent.parent / 'reports' / 'logs'
dir_logs.mkdir(parents=True, exist_ok=True)

logfile_path = dir_logs / f'{script_pth.stem}_{datetime.datetime.now().strftime("%Y%m%dT%H%M%S")}.log'

logger = get_logger(level='INFO', add_stream_handler=True, logfile_path=logfile_path)
```

#### 12.4 Log level guidance

Use log levels consistently and frequently throughout the codebase:

| Level | When to use |
|---|---|
| `DEBUG` | Detailed diagnostic info useful when troubleshooting: variable values, loop counts, intermediate results |
| `INFO` | Normal progress milestones: function entry/exit, key steps completed, record counts |
| `WARNING` | Unexpected but recoverable conditions: missing optional data, fallback behaviour triggered |
| `ERROR` | A specific operation failed and could not complete, but execution can continue |
| `CRITICAL` | A severe failure that will prevent the program from continuing |

Prefer **too many** log messages over too few. A well-logged spatial workflow should let a
developer diagnose a failure from the logfile alone, without needing to reproduce it interactively.

#### 12.5 Logging in `try`/`except` blocks

When catching exceptions, always:

1. Build the error message as a variable
2. Log it at the appropriate level before raising
3. Raise the exception with the message so the caller and any outer handlers see the same text

```python
# ERROR — a specific operation failed; execution may continue in the caller
try:
    result = arcpy.analysis.Buffer(input_fc, output_fc, "100 METERS")
    logger.debug(f"Buffer completed: {output_fc}")
except Exception as e:
    msg = f"Buffer failed for '{input_fc}': {e}"
    logger.error(msg)
    raise RuntimeError(msg) from e
```

```python
# WARNING — unexpected but handled; execution continues normally
try:
    gis = GIS(profile=config.esri.gis_profile)
    logger.info(f"Connected to GIS: {gis.url}")
except Exception as e:
    msg = f"Could not connect to GIS profile '{config.esri.gis_profile}', continuing offline: {e}"
    logger.warning(msg)
    gis = None
```

```python
# CRITICAL — unrecoverable; program cannot continue
try:
    config_path = PROJECT_ROOT / "config" / "config.yml"
    with open(config_path) as f:
        raw = yaml.safe_load(f)
except FileNotFoundError as e:
    msg = f"Configuration file not found at '{config_path}': {e}"
    logger.critical(msg)
    raise FileNotFoundError(msg) from e
```

#### 12.6 ArcPy toolbox logging

When writing Python toolbox tools (`.pyt`), pass `add_arcpy_handler=True` so messages appear
in the ArcGIS Pro geoprocessing pane and results window:

```python
logger = get_logger(__name__, level='INFO', add_arcpy_handler=True)
```
