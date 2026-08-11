"""Acquire and verify the pinned real-data snapshot into ignored data/raw.

Command (download + verify, then record observed checksums in the manifest):

    python -m retail_demand_inventory.data.acquisition \\
        --manifest data/manifests/freshretailnet-real.json \\
        --output-dir data/raw

Offline verification of an already-populated raw directory:

    python -m retail_demand_inventory.data.acquisition \\
        --manifest data/manifests/freshretailnet-real.json \\
        --output-dir data/raw --mode verify

Behavior:

- Resolves the exact revision-pinned HTTPS URLs from the manifest.
- Downloads train.parquet and eval.parquet into the ignored output directory
  (reuses an existing byte-identical local file).
- Verifies existence, EXACT byte size, and the RAW SHA-256 over the untouched
  bytes (raw checksums are computed before any normalization; bytes are never
  rewritten before hashing).
- Verifies pinned-revision metadata: the resolve endpoint must report
  `x-repo-commit == pinned_revision` and `x-linked-size == expected_size`.
- Fails clearly on any mismatch.
- On success records observed sizes/SHA-256 and sets the `snapshot_verified`
  gate in the manifest (unless `--no-update-manifest`).
- Verify-only mode never touches the network.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from .manifests import ManifestError, sha256_file
from .real_manifest import RealSnapshotManifest, load_real_manifest

USER_AGENT = "retail-demand-inventory-decision-engine/0.1.0 (offline audit)"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class AcquisitionError(RuntimeError):
    """Raised when acquisition or verification fails."""


def _fatal(message: str, *, exit_code: int = 1) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def _peek_headers(url: str) -> tuple[str, str]:
    """Fetch HTTP headers for `url` without following redirects.

    Returns (x-repo-commit, x-linked-size) observed on the resolve response.
    """
    request = urllib.request.Request(
        url, method="HEAD", headers={"User-Agent": USER_AGENT}
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=60) as response:
            headers = response.headers
    except urllib.error.HTTPError as exc:
        headers = exc.headers
    return (
        str(headers.get("x-repo-commit", "") or ""),
        str(headers.get("x-linked-size", "") or ""),
    )


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with (
        urllib.request.urlopen(request, timeout=600) as response,
        dest.open("wb") as out,
    ):
        shutil.copyfileobj(response, out)


def _verify_local(
    manifest: RealSnapshotManifest,
    entry,
    local: Path,
) -> tuple[str, str]:
    """Verify one local raw file against expected AND observed checksums.

    A missing observed checksum is a hard failure in real mode.
    Returns (observed_size, observed_sha256).
    """
    if not local.exists():
        raise AcquisitionError(f"raw file {entry.name!r} not found: {local}")
    if entry.observed_size is None or entry.observed_sha256 is None:
        raise AcquisitionError(
            f"raw file {entry.name!r}: observed size/sha256 not recorded; "
            "run acquisition in download mode first"
        )
    size = local.stat().st_size
    digest = sha256_file(local)
    if size != entry.expected_size or digest != entry.expected_sha256:
        raise AcquisitionError(
            f"raw file {entry.name!r}: mismatch with expected metadata "
            f"(size {size} vs {entry.expected_size}; "
            f"sha256 {digest} vs {entry.expected_sha256})"
        )
    if size != entry.observed_size or digest != entry.observed_sha256:
        raise AcquisitionError(
            f"raw file {entry.name!r}: mismatch with observed metadata "
            f"(size {size} vs {entry.observed_size}; "
            f"sha256 {digest} vs {entry.observed_sha256})"
        )
    return str(size), digest


def _acquire_one(
    manifest: RealSnapshotManifest,
    entry,
    output_dir: Path,
    *,
    download: bool,
) -> tuple[str, str]:
    local = output_dir / entry.local_name
    if download:
        repo_commit, linked_size = _peek_headers(entry.url)
        if repo_commit != manifest.pinned_revision:
            raise AcquisitionError(
                f"raw file {entry.name!r}: resolve endpoint reported "
                f"x-repo-commit {repo_commit!r}, expected pinned revision "
                f"{manifest.pinned_revision!r}"
            )
        if linked_size and str(linked_size) != str(entry.expected_size):
            raise AcquisitionError(
                f"raw file {entry.name!r}: resolve endpoint reported "
                f"x-linked-size {linked_size!r}, expected {entry.expected_size!r}"
            )
        if local.exists() and sha256_file(local) == entry.expected_sha256:
            print(f"  {entry.name}: reusing existing verified file {local.name}")
        else:
            print(f"  {entry.name}: downloading {entry.url}")
            local.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=str(output_dir), suffix=".part", delete=False
            ) as tmp:
                tmp_path = Path(tmp.name)
            try:
                _download(entry.url, tmp_path)
                if tmp_path.stat().st_size != entry.expected_size:
                    raise AcquisitionError(
                        f"raw file {entry.name!r}: downloaded size "
                        f"{tmp_path.stat().st_size} != expected {entry.expected_size}"
                    )
                digest = sha256_file(tmp_path)
                if digest != entry.expected_sha256:
                    raise AcquisitionError(
                        f"raw file {entry.name!r}: downloaded sha256 {digest} "
                        f"!= expected {entry.expected_sha256}"
                    )
                tmp_path.replace(local)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
    return _verify_local(manifest, entry, local)


def acquire(
    manifest_path: Path,
    output_dir: Path,
    *,
    download: bool,
    update_manifest: bool,
) -> RealSnapshotManifest:
    """Run acquisition/verification; returns the (possibly updated) manifest."""
    manifest = load_real_manifest(manifest_path)
    if download:
        print(f"acquiring {manifest.dataset_id} @ {manifest.pinned_revision}")
    else:
        print(
            f"verifying local raw files for {manifest.dataset_id} @ {manifest.pinned_revision}"
        )
    output_dir = Path(output_dir)
    for entry in manifest.raw_files:
        observed_size, observed_sha256 = _acquire_one(
            manifest, entry, output_dir, download=download
        )
        manifest = manifest.with_observed(entry.name, observed_size, observed_sha256)
    manifest = manifest.with_snapshot_verified()
    print(
        "all raw files verified: existence, exact byte size, raw sha256, pinned revision"
    )
    if download and update_manifest:
        manifest.save(manifest_path)
        print(f"manifest updated: {manifest_path}")
    elif download and not update_manifest:
        print("manifest not updated (--no-update-manifest)")
    else:
        print("verify-only: manifest left unchanged")
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Acquire and verify the pinned real-data snapshot (offline after first download)."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--mode",
        choices=("download", "verify"),
        default="download",
        help="download+verify (network) or local verify-only",
    )
    parser.add_argument(
        "--no-update-manifest",
        action="store_true",
        help="do not write observed checksums/gates back to the manifest",
    )
    args = parser.parse_args(argv)

    try:
        acquire(
            args.manifest,
            args.output_dir,
            download=args.mode == "download",
            update_manifest=not args.no_update_manifest,
        )
    except (ManifestError, AcquisitionError, urllib.error.URLError, OSError) as exc:
        _fatal(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
