"""Loads config.toml and resolves the vault directory layout.

Never log the token or the resolved paths' contents - only this module
should read config.toml, and callers get back a plain dataclass.
"""
from __future__ import annotations

import secrets
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_TOML = """\
[paths]
vault_dir = "~/vault"

[ingest]
poll_interval_s = 60
stable_polls = 2

[ocr]
langs = "eng"
min_chars_per_page = 100
rasterize_dpi = 200

[tagger]
window_start = "01:00"
window_end = "06:00"

[llm]
local_url = "http://127.0.0.1:8080"
upstream_url = ""

[api]
bind_host = "127.0.0.1"
bind_port = 8090
token = ""
"""


@dataclass
class VaultPaths:
    root: Path
    inbox: Path
    store: Path
    text: Path
    redacted: Path
    db_dir: Path
    logs: Path
    db_file: Path
    config_file: Path
    names_file: Path

    @classmethod
    def from_root(cls, root: Path) -> "VaultPaths":
        root = root.expanduser()
        return cls(
            root=root,
            inbox=root / "inbox",
            store=root / "store",
            text=root / "text",
            redacted=root / "redacted",
            db_dir=root / "db",
            logs=root / "logs",
            db_file=root / "db" / "vault.sqlite",
            config_file=root / "config.toml",
            names_file=root / "names.txt",
        )

    def all_dirs(self):
        return [self.inbox, self.store, self.text, self.redacted, self.db_dir, self.logs]


@dataclass
class Config:
    paths: VaultPaths
    poll_interval_s: int = 60
    stable_polls: int = 2
    ocr_langs: str = "eng"
    min_chars_per_page: int = 100
    rasterize_dpi: int = 200
    tagger_window_start: str = "01:00"
    tagger_window_end: str = "06:00"
    llm_local_url: str = "http://127.0.0.1:8080"
    llm_upstream_url: str = ""
    api_bind_host: str = "127.0.0.1"
    api_bind_port: int = 8090
    api_token: str = ""


def load_config(config_path: str | Path = "~/vault/config.toml") -> Config:
    path = Path(config_path).expanduser()
    with open(path, "rb") as f:
        data = tomllib.load(f)

    paths_section = data.get("paths", {})
    vault_dir = Path(paths_section.get("vault_dir", "~/vault"))
    paths = VaultPaths.from_root(vault_dir)

    ingest = data.get("ingest", {})
    ocr = data.get("ocr", {})
    tagger = data.get("tagger", {})
    llm = data.get("llm", {})
    api = data.get("api", {})

    return Config(
        paths=paths,
        poll_interval_s=int(ingest.get("poll_interval_s", 60)),
        stable_polls=int(ingest.get("stable_polls", 2)),
        ocr_langs=str(ocr.get("langs", "eng")),
        min_chars_per_page=int(ocr.get("min_chars_per_page", 100)),
        rasterize_dpi=int(ocr.get("rasterize_dpi", 200)),
        tagger_window_start=str(tagger.get("window_start", "01:00")),
        tagger_window_end=str(tagger.get("window_end", "06:00")),
        llm_local_url=str(llm.get("local_url", "http://127.0.0.1:8080")),
        llm_upstream_url=str(llm.get("upstream_url", "")),
        api_bind_host=str(api.get("bind_host", "127.0.0.1")),
        api_bind_port=int(api.get("bind_port", 8090)),
        api_token=str(api.get("token", "")),
    )


def init_vault_layout(vault_dir: str | Path = "~/vault") -> VaultPaths:
    """Creates the vault directory tree, config.toml, and names.txt if missing.

    Idempotent: safe to call on every deploy. Never overwrites an existing
    config.toml (it may hold a token already handed to the owner).
    """
    paths = VaultPaths.from_root(Path(vault_dir))
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.root.chmod(0o700)
    for d in paths.all_dirs():
        d.mkdir(parents=True, exist_ok=True)
        d.chmod(0o700)

    token_printed = None
    if not paths.config_file.exists():
        token = secrets.token_urlsafe(32)
        content = DEFAULT_CONFIG_TOML.replace('token = ""', f'token = "{token}"')
        content = content.replace(
            'vault_dir = "~/vault"', f'vault_dir = "{vault_dir}"'
        )
        paths.config_file.write_text(content)
        paths.config_file.chmod(0o600)
        token_printed = token

    if not paths.names_file.exists():
        paths.names_file.write_text(
            "# one name or phrase per line, always redacted (case-insensitive)\n"
        )
        paths.names_file.chmod(0o600)

    return paths, token_printed
