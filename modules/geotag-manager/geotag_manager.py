"""
efps-geotag-manager
-------------------
In-place GPS metadata management for image files.

Uses PyExifTool to read and write GPS coordinates directly on images
without re-encoding pixel data or corrupting non-GPS metadata fields.

Features:
  - Set/update GPSLatitude, GPSLatitudeRef, GPSLongitude, GPSLongitudeRef
  - Convert decimal degree coordinates to EXIF DMS format
  - Optional backup creation before modification
  - Runtime verification of exiftool binary availability
  - Batch processing of image directories
  - CLI interface for single-file and directory operations

Data Safety:
  - Only GPS tags are modified; all other metadata is untouched
  - No pixel re-encoding occurs
  - In-place updates via PyExifTool's native tag writing

Author: Kairo-style implementation for EFPS Automations
Version: 1.0.0
"""

import os
import sys
import logging
import shutil
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("[%(levelname)s] %(name)s.%(funcName)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS: set = {
    ".jpg", ".jpeg", ".tiff", ".tif", ".png",
    ".heic", ".heif", ".raw", ".cr2", ".nef", ".arw", ".dng",
}

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class GeotagError(Exception):
    """Base exception for geotag-manager operations."""
    pass


class ExifToolNotAvailableError(GeotagError):
    """Raised when the exiftool binary is not found in system PATH."""
    pass


class CoordinateConversionError(GeotagError):
    """Raised when GPS coordinate conversion fails."""
    pass


class MetadataReadError(GeotagError):
    """Raised when image metadata cannot be read."""
    pass


class MetadataWriteError(GeotagError):
    """Raised when GPS metadata cannot be written to an image."""
    pass

# ---------------------------------------------------------------------------
# ExifTool Verification
# ---------------------------------------------------------------------------

def verify_exiftool() -> str:
    """
    Verify that the exiftool binary is available in the system PATH.

    Returns:
        str: Absolute path to the exiftool binary.

    Raises:
        ExifToolNotAvailableError: If exiftool is not found in PATH.
    """
    exiftool_path = shutil.which("exiftool")
    if exiftool_path is None:
        raise ExifToolNotAvailableError(
            "exiftool binary not found in system PATH. "
            "Install it using:\n"
            "  - macOS:            brew install exiftool\n"
            "  - Linux (Debian/Ubuntu): sudo apt install libimage-exiftool-perl\n"
            "  - Windows:          download from https://exiftool.org/"
        )
    logger.info(f"[verify] exiftool found at: {exiftool_path}")
    return exiftool_path

# ---------------------------------------------------------------------------
# Coordinate Conversion
# ---------------------------------------------------------------------------

def decimal_to_dms(decimal_degrees: float) -> Tuple[int, int, float]:
    """
    Convert decimal degrees to degrees, minutes, seconds (DMS) format.

    The absolute value of the input is used for the calculation.
    Direction (N/S/E/W) is determined separately from the sign.

    Args:
        decimal_degrees: Latitude or longitude in decimal degrees.

    Returns:
        Tuple of (degrees, minutes, seconds) where degrees and minutes
        are non-negative integers and seconds is a non-negative float.

    Raises:
        CoordinateConversionError: If the input is not a valid number.
    """
    try:
        d = abs(float(decimal_degrees))
        degrees = int(d)
        minutes_float = (d - degrees) * 60.0
        minutes = int(minutes_float)
        seconds = (minutes_float - minutes) * 60.0
        return degrees, minutes, seconds
    except (ValueError, TypeError) as exc:
        raise CoordinateConversionError(
            f"Cannot convert '{decimal_degrees}' to DMS: {exc}"
        ) from exc


def float_to_gps_tags(
    latitude: float,
    longitude: float,
) -> Dict[str, str]:
    """
    Convert decimal degree GPS coordinates to an EXIF GPS tag dictionary.

    Produces four tags compatible with ExifTool:
      - GPSLatitude:      DMS string, e.g. ``"37 46 29.6400"``
      - GPSLatitudeRef:   ``"N"`` or ``"S"``
      - GPSLongitude:     DMS string, e.g. ``"122 25 10.0800"``
      - GPSLongitudeRef:  ``"E"`` or ``"W"``

    Args:
        latitude:  Latitude  in decimal degrees (-90 to 90).
                   Positive = North, Negative = South.
        longitude: Longitude in decimal degrees (-180 to 180).
                   Positive = East,  Negative = West.

    Returns:
        Dict with four GPS tag key-value pairs.

    Raises:
        CoordinateConversionError: If coordinates are out of valid range.
    """
    if not (-90.0 <= latitude <= 90.0):
        raise CoordinateConversionError(
            f"Latitude {latitude} is out of valid range (-90 to 90)."
        )
    if not (-180.0 <= longitude <= 180.0):
        raise CoordinateConversionError(
            f"Longitude {longitude} is out of valid range (-180 to 180)."
        )

    # Direction references from sign
    lat_ref = "N" if latitude >= 0 else "S"
    lon_ref = "E" if longitude >= 0 else "W"

    # Convert to DMS (uses absolute value internally)
    lat_d, lat_m, lat_s = decimal_to_dms(latitude)
    lon_d, lon_m, lon_s = decimal_to_dms(longitude)

    tags: Dict[str, str] = {
        "GPSLatitude": f"{lat_d} {lat_m} {lat_s:.4f}",
        "GPSLatitudeRef": lat_ref,
        "GPSLongitude": f"{lon_d} {lon_m} {lon_s:.4f}",
        "GPSLongitudeRef": lon_ref,
    }

    logger.info(
        f"[gps] ({latitude}, {longitude}) -> "
        f"Lat: {lat_d}\u00b0{lat_m}'{lat_s:.2f}\" {lat_ref}, "
        f"Lon: {lon_d}\u00b0{lon_m}'{lon_s:.2f}\" {lon_ref}"
    )
    return tags

# ---------------------------------------------------------------------------
# Metadata Read Operations
# ---------------------------------------------------------------------------

def get_gps_metadata(file_path: str) -> Optional[Dict[str, str]]:
    """
    Read current GPS metadata from an image file.

    Args:
        file_path: Absolute or relative path to the image file.

    Returns:
        Dict containing GPS tag names and values if GPS data exists.
        None if no GPS tags are present.

    Raises:
        MetadataReadError: If metadata cannot be read from the file.
    """
    from exiftool import ExifToolHelper  # lazy import — only needed at runtime

    try:
        with ExifToolHelper() as et:
            metadata_list = et.get_metadata(file_path)

            if not metadata_list or len(metadata_list) == 0:
                return None

            metadata = metadata_list[0]

            gps_keys = [
                "GPSLatitude", "GPSLatitudeRef",
                "GPSLongitude", "GPSLongitudeRef",
                "GPSAltitude", "GPSAltitudeRef",
            ]

            gps_tags: Dict[str, str] = {}
            for key in gps_keys:
                if key in metadata:
                    gps_tags[key] = metadata[key]

            return gps_tags if gps_tags else None

    except Exception as exc:
        raise MetadataReadError(
            f"Failed to read GPS metadata from '{file_path}': {exc}"
        ) from exc


def get_all_metadata(file_path: str) -> Dict[str, Any]:
    """
    Read **all** metadata from an image file.

    Primarily used for testing to verify non-GPS metadata preservation.

    Args:
        file_path: Absolute or relative path to the image file.

    Returns:
        Dict containing every metadata tag and its value.

    Raises:
        MetadataReadError: If metadata cannot be read.
    """
    from exiftool import ExifToolHelper  # lazy import

    try:
        with ExifToolHelper() as et:
            metadata_list = et.get_metadata(file_path)

            if not metadata_list or len(metadata_list) == 0:
                return {}

            return metadata_list[0]

    except Exception as exc:
        raise MetadataReadError(
            f"Failed to read metadata from '{file_path}': {exc}"
        ) from exc

# ---------------------------------------------------------------------------
# Metadata Write Operations
# ---------------------------------------------------------------------------

def set_gps_metadata(
    file_path: str,
    latitude: float,
    longitude: float,
    create_backup: bool = False,
) -> bool:
    """
    Set or update GPS coordinates on an image file **in-place**.

    Only GPS tags are written.  All other metadata (EXIF, IPTC, XMP,
    MakerNotes, embedded thumbnails, color profiles) remains untouched.
    No pixel data is re-encoded.

    Args:
        file_path:     Path to the image file.
        latitude:      GPS latitude  in decimal degrees (-90 to 90).
        longitude:     GPS longitude in decimal degrees (-180 to 180).
        create_backup: If True, ExifTool creates a backup
                       (e.g. ``file.jpg_original``).
                       If False, the original file is overwritten directly.

    Returns:
        bool: True when GPS tags are successfully written.

    Raises:
        MetadataWriteError:  If GPS tags cannot be written.
        CoordinateConversionError: If coordinates are invalid.
    """
    from exiftool import ExifToolHelper  # lazy import

    # Convert coordinates to EXIF DMS tags
    gps_tags = float_to_gps_tags(latitude, longitude)

    # Build ExifTool parameters
    params: List[str] = []
    if not create_backup:
        params.append("-overwrite_original")

    try:
        with ExifToolHelper() as et:
            et.set_tags(
                file_path,
                gps_tags,
                params=params if params else None,
            )

        logger.info(
            f"[write] GPS updated on '{file_path}': ({latitude}, {longitude})"
        )
        return True

    except Exception as exc:
        raise MetadataWriteError(
            f"Failed to write GPS metadata to '{file_path}': {exc}"
        ) from exc

# ---------------------------------------------------------------------------
# Directory Scanning
# ---------------------------------------------------------------------------

def find_images(directory: str) -> List[str]:
    """
    Find all supported image files in a directory (non-recursive).

    Args:
        directory: Path to the directory to scan.

    Returns:
        Sorted list of absolute paths to supported image files.

    Raises:
        GeotagError: If the directory does not exist or is not a directory.
    """
    dir_path = Path(directory)

    if not dir_path.exists():
        raise GeotagError(f"Directory does not exist: {directory}")

    if not dir_path.is_dir():
        raise GeotagError(f"Path is not a directory: {directory}")

    images: List[str] = []
    for file_path in sorted(dir_path.iterdir()):
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            images.append(str(file_path.resolve()))

    logger.info(f"[scan] Found {len(images)} image(s) in '{directory}'")
    return images

# ---------------------------------------------------------------------------
# Batch Processing
# ---------------------------------------------------------------------------

def process_directory(
    directory: str,
    latitude: float,
    longitude: float,
    create_backup: bool = False,
) -> Dict[str, Any]:
    """
    Process all images in a directory, setting GPS coordinates on each.

    Args:
        directory:      Path to the directory containing images.
        latitude:       GPS latitude  in decimal degrees.
        longitude:      GPS longitude in decimal degrees.
        create_backup:  If True, create backup files before modifying.

    Returns:
        Dict with processing summary::

            {
                "processed": int,   # total images found
                "updated":   int,   # successfully updated
                "failed":    int,   # failed to update
                "files": {
                    "<path>": {"status": "updated", ...} | {"status": "failed", "error": ...}
                }
            }
    """
    # Verify exiftool binary is available
    verify_exiftool()

    # Locate images
    images = find_images(directory)

    if not images:
        logger.warning(f"[process] No supported images found in '{directory}'")
        return {
            "processed": 0,
            "updated": 0,
            "failed": 0,
            "files": {},
        }

    results: Dict[str, Any] = {
        "processed": len(images),
        "updated": 0,
        "failed": 0,
        "files": {},
    }

    for image_path in images:
        try:
            set_gps_metadata(image_path, latitude, longitude, create_backup)
            results["updated"] += 1
            results["files"][image_path] = {
                "status": "updated",
                "latitude": latitude,
                "longitude": longitude,
            }
        except Exception as exc:
            results["failed"] += 1
            results["files"][image_path] = {
                "status": "failed",
                "error": str(exc),
            }
            logger.error(f"[process] Failed to process '{image_path}': {exc}")

    logger.info(
        f"[process] Complete. {results['updated']}/{results['processed']} updated, "
        f"{results['failed']} failed."
    )
    return results

# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for CLI usage."""
    parser = argparse.ArgumentParser(
        prog="geotag-manager",
        description="Set or update GPS coordinates on image files.",
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Path to a single image file to update.",
    )
    parser.add_argument(
        "--dir",
        type=str,
        help="Path to a directory of images to update.",
    )
    parser.add_argument(
        "--lat",
        type=float,
        required=True,
        help="GPS latitude in decimal degrees (-90 to 90).",
    )
    parser.add_argument(
        "--lon",
        type=float,
        required=True,
        help="GPS longitude in decimal degrees (-180 to 180).",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        default=False,
        help="Create backup files before modifying images.",
    )
    parser.add_argument(
        "--read",
        type=str,
        metavar="FILE",
        help="Read and print all metadata from the given image file.",
    )
    parser.add_argument(
        "--read-gps",
        type=str,
        metavar="FILE",
        help="Read and print GPS metadata from the given image file.",
    )
    return parser


def main() -> int:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    try:
        # Verify exiftool
        verify_exiftool()

        # Read-only modes
        if args.read:
            metadata = get_all_metadata(args.read)
            for key, value in sorted(metadata.items()):
                print(f"  {key}: {value}")
            return 0

        if args.read_gps:
            gps = get_gps_metadata(args.read_gps)
            if gps:
                for key, value in sorted(gps.items()):
                    print(f"  {key}: {value}")
            else:
                print("  No GPS metadata found.")
            return 0

        # Single-file mode
        if args.file:
            set_gps_metadata(args.file, args.lat, args.lon, args.backup)
            print(f"GPS set on '{args.file}': ({args.lat}, {args.lon})")
            return 0

        # Directory mode
        if args.dir:
            results = process_directory(args.dir, args.lat, args.lon, args.backup)
            print(f"\nProcessed: {results['processed']}")
            print(f"Updated:   {results['updated']}")
            print(f"Failed:    {results['failed']}")
            return 0 if results["failed"] == 0 else 1

        parser.print_help()
        return 0

    except GeotagError as exc:
        logger.error(f"[cli] {exc}")
        return 1
    except KeyboardInterrupt:
        logger.info("[cli] Interrupted by user.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
