"""Deterministic serialisation of generated datasets (byte-identical for the same seed)."""

import csv
import hashlib
import io
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GENERATOR_VERSION = "1"
DISCLAIMER = (
    "SYNTHETIC DATA. Generated for development and testing. All organisations, identifiers and "
    "amounts are fictional. VAT numbers and IBANs are deliberately invalid. Not tax or legal data."
)


def to_json_bytes(data: Any) -> bytes:
    return (json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def to_csv_bytes(header: Sequence[str], rows: Iterable[Sequence[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


@dataclass
class Dataset:
    """A set of named files plus a manifest describing how they were generated."""

    kind: str
    seed: int
    profile: dict[str, Any]
    files: dict[str, bytes] = field(default_factory=dict)

    def manifest(self) -> dict[str, Any]:
        return {
            "synthetic": True,
            "disclaimer": DISCLAIMER,
            "kind": self.kind,
            "generator_version": GENERATOR_VERSION,
            "seed": self.seed,
            "profile": self.profile,
            "files": {
                name: hashlib.sha256(content).hexdigest()
                for name, content in sorted(self.files.items())
            },
        }

    def all_files(self) -> dict[str, bytes]:
        return {**self.files, "manifest.json": to_json_bytes(self.manifest())}

    def fingerprint(self) -> str:
        """SHA-256 over every file (including the manifest), for determinism checks."""
        digest = hashlib.sha256()
        for name, content in sorted(self.all_files().items()):
            digest.update(name.encode() + b"\0" + content + b"\0")
        return digest.hexdigest()

    def write(self, directory: Path) -> list[Path]:
        directory.mkdir(parents=True, exist_ok=True)
        written = []
        for name, content in sorted(self.all_files().items()):
            path = directory / name
            path.write_bytes(content)
            written.append(path)
        return written
