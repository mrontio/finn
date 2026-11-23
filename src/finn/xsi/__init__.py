############################################################################
# Copyright (C) 2025, Advanced Micro Devices, Inc.
# All rights reserved.
# Portions of this content consist of AI generated content.
#
# SPDX-License-Identifier: BSD-3-Clause
#
# ##########################################################################
"""FINN XSI (Xilinx Simulation Interface) support module

This module provides utilities for RTL simulation support via finn_xsi.
The finn_xsi extension must be built separately using the setup command.

Usage:
    # Check if XSI support is available
    from finn import xsi
    if xsi.is_available():
        import finn_xsi.adapter
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional


def is_available() -> bool:
    """Check if XSI (RTL simulation) support is available.

    Returns:
        bool: True if finn_xsi can be imported, False otherwise
    """
    # Check if xsi.so exists
    xsi_path = Path(os.environ["FINN_ROOT"]) / "finn_xsi"
    xsi_so = xsi_path / "xsi.so"
    if not xsi_so.exists():
        _record_unavailable(
            f"xsi.so not found at {xsi_so}. Build it with: python -m finn.xsi.setup"
        )
        return False

    # Try loading the modules (this will cache them if successful)
    return _load_modules()


def unavailable_reason() -> Optional[str]:
    """Why the last is_available()/_load_modules() call failed, or None if it did not.

    Callers that cache `xsi if xsi.is_available() else None` lose the ImportError
    raised by the function wrappers below, and only fail much later with an
    unhelpful 'NoneType' has no attribute ... -- use this to report the cause.
    """
    return _load_error


# Cache for loaded modules
_adapter_module: Optional[Any] = None
_sim_engine_module: Optional[Any] = None
_xsi_module: Optional[Any] = None

# Explanation of the most recent load failure, surfaced via unavailable_reason()
_load_error: Optional[str] = None
_warned_once = False


def _record_unavailable(reason: str) -> None:
    """Store the reason XSI is unavailable and warn about it once."""
    global _load_error, _warned_once
    _load_error = reason
    if not _warned_once:
        _warned_once = True
        logging.warning(f"RTL simulation (XSI) is unavailable: {reason}")


def _diagnose_import_error(exc: ImportError, xsi_so: Path) -> str:
    """Turn a raw finn_xsi ImportError into something actionable."""
    msg = str(exc)

    # xsi.so is a compiled extension living in the (bind-mounted) checkout, so it
    # outlives the container that built it. After a base-image Python upgrade the
    # stale object is still on disk but no longer loadable -- by far the most
    # common cause, and the least obvious from the raw message.
    if "Python version mismatch" in msg or "undefined symbol: Py" in msg:
        return (
            f"{xsi_so} was compiled for a different Python than the running "
            f"interpreter ({sys.version.split()[0]}). This usually means the .so was "
            "built inside an older FINN container and is now stale. Rebuild it with: "
            "python -m finn.xsi.setup --force"
        )

    # The simkernel is dlopen'd from the Vivado install rather than linked, so a
    # missing one means Vivado was never sourced in this shell.
    if "libxv_simulator_kernel" in msg or "XILINX_VIVADO" in msg:
        return (
            f"could not load the Vivado simulation kernel ({msg}). Ensure Vivado is "
            "sourced and XILINX_VIVADO is set."
        )

    return f"{msg}. If finn_xsi was never built, run: python -m finn.xsi.setup"


def _load_modules() -> bool:
    """Load finn_xsi modules if available."""
    global _adapter_module, _sim_engine_module, _xsi_module

    if _adapter_module is not None:
        return True

    xsi_path = Path(os.environ["FINN_ROOT"]) / "finn_xsi"
    xsi_so = xsi_path / "xsi.so"

    if not xsi_so.exists():
        _record_unavailable(
            f"xsi.so not found at {xsi_so}. Build it with: python -m finn.xsi.setup"
        )
        return False

    # Temporarily add to path for import
    path_added = str(xsi_path) not in sys.path
    if path_added:
        sys.path.insert(0, str(xsi_path))

    try:
        # Imports must be inside function: modules require dynamic path setup
        # and may not exist if finn_xsi extension is not built
        import finn_xsi.adapter  # noqa: PLC0415
        import finn_xsi.sim_engine  # noqa: PLC0415
        import xsi  # noqa: PLC0415

        _xsi_module = xsi
        _adapter_module = finn_xsi.adapter
        _sim_engine_module = finn_xsi.sim_engine

        return True
    except ImportError as e:
        _record_unavailable(_diagnose_import_error(e, xsi_so))
        return False
    except Exception as e:
        # Catch any unexpected errors during module loading
        _record_unavailable(f"unexpected {type(e).__name__} loading finn_xsi: {e}")
        return False
    finally:
        # Remove from path if we added it
        if path_added and str(xsi_path) in sys.path:
            try:
                sys.path.remove(str(xsi_path))
            except ValueError:
                pass  # Path was already removed somehow


# List of functions to wrap from finn_xsi.adapter
_ADAPTER_FUNCTIONS = [
    "locate_glbl",
    "compile_sim_obj",
    "get_simkernel_so",
    "load_sim_obj",
    "reset_rtlsim",
    "close_rtlsim",
    "rtlsim_multi_io",
]


def __getattr__(name: str) -> Any:
    """Dynamically wrap finn_xsi.adapter functions."""
    if name in _ADAPTER_FUNCTIONS:

        def wrapper(*args, **kwargs):
            if not _load_modules():
                raise ImportError(f"finn_xsi not available: {unavailable_reason()}")
            return getattr(_adapter_module, name)(*args, **kwargs)

        wrapper.__name__ = name
        wrapper.__doc__ = f"Wrapper for finn_xsi.adapter.{name}"
        return wrapper
    if name == "SimulationError":
        if not _load_modules():
            raise ImportError("finn_xsi not available. Run: python -m finn.xsi.setup")
        return _sim_engine_module.SimulationError
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


# SimEngine class wrapper
class SimEngine:
    """Wrapper for finn_xsi.sim_engine.SimEngine."""

    def __init__(self, *args, **kwargs):
        if not _load_modules():
            raise ImportError(f"finn_xsi not available: {unavailable_reason()}")
        self._engine = _sim_engine_module.SimEngine(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._engine, name)
