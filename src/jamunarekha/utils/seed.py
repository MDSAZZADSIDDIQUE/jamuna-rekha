"""Deterministic seeding.

CLAUDE.md §4: *"Randomness: seed everything, record the seed in the run
config."* Every entry point calls :func:`seed_everything` with
``cfg.project.seed`` before touching data or model.
"""

from __future__ import annotations

import os
import random

import numpy as np


def seed_everything(seed: int, deterministic: bool = True) -> int:
    """Seed Python, NumPy and (if importable) PyTorch.

    Parameters
    ----------
    seed
        The integer seed. Recorded in the run config so a run is reproducible.
    deterministic
        If True, ask cuDNN for deterministic kernels. Costs some speed; on the
        A100 budget the reproducibility is worth more than the few percent.

    Returns
    -------
    int
        The seed, so callers can log it in one line.
    """
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch

        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        if deterministic:
            torch.backends.cudnn.deterministic = True
            torch.backends.cudnn.benchmark = False
    except ImportError:  # torch is not needed for the Stage 1/2/4 scripts
        pass
    return seed
