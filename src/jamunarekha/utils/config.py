"""Configuration loading.

All paths in the project come from ``configs/*.yaml`` (CLAUDE.md §4: *"No
hard-coded paths"*). :func:`load_config` merges an override file on top of
``base.yaml`` and resolves every entry of ``cfg.paths`` to an absolute
:class:`~pathlib.Path` rooted at the repository.
"""

from __future__ import annotations

from pathlib import Path

from omegaconf import DictConfig, OmegaConf

# repo root = .../src/jamunarekha/utils/config.py -> up four levels
REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "configs"


def load_config(override: str | None = None, base: str = "base.yaml") -> DictConfig:
    """Load ``base.yaml`` and merge ``override`` (e.g. ``"local.yaml"``) on top.

    Parameters
    ----------
    override
        File name inside ``configs/``, or ``None`` for the base config alone.
    base
        The base config file name.

    Returns
    -------
    DictConfig
        The merged config. ``cfg.paths.*`` are absolute POSIX path strings.
    """
    cfg = OmegaConf.load(CONFIG_DIR / base)
    if override:
        cfg = OmegaConf.merge(cfg, OmegaConf.load(CONFIG_DIR / override))

    root = REPO_ROOT if cfg.paths.root in (".", "") else Path(cfg.paths.root)
    for key, value in cfg.paths.items():
        if key == "root":
            cfg.paths[key] = str(root)
        else:
            cfg.paths[key] = str((root / value).resolve())
    return cfg  # type: ignore[return-value]


def path_of(cfg: DictConfig, key: str, *parts: str, mkdir: bool = False) -> Path:
    """Return ``cfg.paths[key]`` joined with ``parts``, optionally creating it."""
    p = Path(cfg.paths[key]).joinpath(*parts)
    if mkdir:
        (p if not p.suffix else p.parent).mkdir(parents=True, exist_ok=True)
    return p
