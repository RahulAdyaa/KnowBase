"""Environment quirks for model downloads.

The sandbox egress proxy sets no_proxy/NO_PROXY to values that httpx2 (used by
huggingface_hub) cannot parse ("Invalid port: ':1]'"). Egress itself requires
the proxy, so we keep http_proxy/https_proxy and drop only the no_proxy lists
around huggingface_hub calls.
"""

import os
from contextlib import contextmanager


@contextmanager
def hf_download_env():
    """Sanitize proxy env for huggingface_hub downloads."""
    saved = {}
    for var in ("no_proxy", "NO_PROXY"):
        if var in os.environ:
            saved[var] = os.environ.pop(var)
    try:
        yield
    finally:
        os.environ.update(saved)
