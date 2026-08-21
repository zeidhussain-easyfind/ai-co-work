"""
efps-geotag-manager — GPS metadata management for image files.

Provides coordinate conversion, EXIF GPS tag generation, image discovery,
and ExifTool-based metadata read/write operations.
"""

import os
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

try:
    import exiftool
except ImportError:
    exiftool = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class GeotagError(Exception):
    """Base exception for geotag-manager errors."""
    pass


class ExifToolNotAvailableError(GeotagError):
    """Raised when ExifTool binary cannot be located."""
    pass


class CoordinateConversionError(GeotagError):
    """Raised when coordinate conversion fails due to invalid input."""
    pass


class MetadataReadError(GeotagError):
    """Raised when reading metadata from a file fails."""
    pass


class MetadataWriteError(GeotagError):
    """Raised when writing metadata to a file fails."""
    pass


# ---------------------------------------------------------------------------
# Supported Extensions
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS: Set[str] = {
    # Common formats
    ".jpg", ".jpeg", ".png", ".tiff", ".tif",
    # RAW formats
    ".cr2", ".nef", ".arw", ".dng", ".raf", ".orf", ".rw2", ".pef", ".srw",
    # Mobile formats
    ".heic", ".heif",
    # Others
    ".bmp", ".gif", ".webp", ".jp2", ".j2k", ".jpf", ".jpx", ".jpm", ".mj2",
}


# ---------------------------------------------------------------------------
# Coordinate Conversion
# ---------------------------------------------------------------------------
def decimal_to_dms(decimal_degrees: Union[float, int]) -> Tuple[int, int, float]:
    """
    Convert decimal degrees to degrees, minutes, seconds.

    Args:
        decimal_degrees: Latitude or longitude in decimal degrees.

    Returns:
        Tuple of (degrees, minutes, seconds) as (int, int, float).

    Raises:
        CoordinateConversionError: If input cannot be converted to float.
    """
    try:
        value = float(decimal_degrees)
    except (TypeError, ValueError) as exc:
        raise CoordinateConversionError(f"Cannot convert {decimal_degrees!r} to float") from exc

    sign = -1 if value < 0 else 1
    abs_value = abs(value)

    degrees = int(abs_value)
    minutes_full = (abs_value - degrees) * 60
    minutes = int(minutes_full)
    seconds = (minutes_full - minutes) * 60

    return degrees, minutes, round(seconds, 2)


def float_to_gps_tags(latitude: float, longitude: float) -> Dict[str, str]:
    """
    Convert decimal latitude/longitude to EXIF GPS tag dictionary.

    Args:
        latitude: Latitude in decimal degrees (-90 to 90).
        longitude: Longitude in decimal degrees (-180 to 180).

    Returns:
        Dictionary with keys: GPSLatitude, GPSLatitudeRef, GPSLongitude, GPSLongitudeRef.

    Raises:
        CoordinateConversionError: If coordinates are out of valid range.
    """
    # Validate latitude
    if not -90.0 <= latitude <= 90.0:
        raise CoordinateConversionError(
            f"Latitude {latitude} out of valid range [-90, 90]"
        )

    # Validate longitude
    if not -180.0 <= longitude <= 180.0:
        raise CoordinateConversionError(
            f"Longitude {longitude} out of valid range [-180, 180]"
        )

    # Convert to DMS
    lat_deg, lat_min, lat_sec = decimal_to_dms(latitude)
    lon_deg, lon_min, lon_sec = decimal_to_dms(longitude)

    # Determine references
    lat_ref = "N" if latitude >= 0 else "S"
    lon_ref = "E" if longitude >= 0 else "W"

    # Format as EXIF DMS strings: "DD MM SS.ss"
    gps_latitude = f"{lat_deg} {lat_min} {lat_sec:.2f}"
    gps_longitude = f"{lon_deg} {lon_min} {lon_sec:.2f}"

    return {
        "GPSLatitude": gps_latitude,
        "GPSLatitudeRef": lat_ref,
        "GPSLongitude": gps_longitude,
        "GPSLongitudeRef": lon_ref,
    }


# ---------------------------------------------------------------------------
# Image Discovery
# ---------------------------------------------------------------------------
def find_images(directory: Union[str, Path]) -> List[str]:
    """
    Find all supported image files in a directory (non-recursive).

    Args:
        directory: Path to directory to scan.

    Returns:
        Sorted list of absolute file paths.

    Raises:
        GeotagError: If directory does not exist or is not a directory.
    """
    path = Path(directory).resolve()

    if not path.exists():
        raise GeotagError(f"Directory does not exist: {directory}")

    if not path.is_dir():
        raise GeotagError(f"Path is not a directory: {directory}")

    images: List[str] = []
    for entry in path.iterdir():
        if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS:
            images.append(str(entry.absolute()))

    return sorted(images)

# ---------------------------------------------------------------------------
# ExifTool Integration
# ---------------------------------------------------------------------------
def _get_exiftool_path() -> str:
    """
    Locate the exiftool binary.

    Returns:
        Absolute path to exiftool executable.

    Raises:
        ExifToolNotAvailableError: If exiftool is not found in PATH.
    """
    exiftool_path = shutil.which("exiftool")
    if exiftool_path is None:
        raise ExifToolNotAvailableError(
            "ExifTool not found. Please install exiftool and ensure it is in PATH."
        )
    return exiftool_path


def verify_exiftool() -> str:
    """
    Verify ExifTool is available and return its path.

    Returns:
        Absolute path to exiftool executable.

    Raises:
        ExifToolNotAvailableError: If exiftool is not found.
    """
    return _get_exiftool_path()


def _run_exiftool(args: List[str]) -> str:
    """
    Run exiftool with given arguments and return stdout.

    Args:
        args: List of arguments to pass to exiftool.

    Returns:
        Standard output as string.

    Raises:
        MetadataReadError: If exiftool execution fails.
    """
    exiftool_path = _get_exiftool_path()
    cmd = [exiftool_path] + args

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise MetadataReadError(
            f"ExifTool failed with exit code {exc.returncode}: {exc.stderr.strip()}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MetadataReadError("ExifTool timed out after 30 seconds") from exc


def get_all_metadata(image_path: Union[str, Path]) -> Dict[str, str]:
    """
    Read all metadata from an image file using ExifTool.

    Args:
        image_path: Path to image file.

    Returns:
        Dictionary of tag names to values.

    Raises:
        MetadataReadError: If reading metadata fails.
    """
    path = Path(image_path)
    if not path.is_file():
        raise MetadataReadError(f"File not found: {image_path}")

    # Use -j for JSON output, -G for group names, -n for numeric values where applicable
    output = _run_exiftool(["-j", "-G", "-n", str(path)])

    import json
    try:
        data = json.loads(output)
        if not data:
            return {}
        # ExifTool returns a list of objects (one per file)
        metadata = data[0]
        # Flatten group names: "EXIF:Make" -> "Make", but keep group for disambiguation
        # We'll use the full tag name as key
        return {k: str(v) for k, v in metadata.items() if k != "SourceFile"}
    except json.JSONDecodeError as exc:
        raise MetadataReadError(f"Failed to parse ExifTool JSON output: {exc}") from exc


def get_gps_metadata(image_path: Union[str, Path]) -> Optional[Dict[str, str]]:
    """
    Read GPS metadata from an image file.

    Args:
        image_path: Path to image file.

    Returns:
        Dictionary with GPS tags, or None if no GPS data present.

    Raises:
        MetadataReadError: If reading metadata fails.
    """
    all_meta = get_all_metadata(image_path)

    gps_keys = {
        "GPSLatitude", "GPSLatitudeRef",
        "GPSLongitude", "GPSLongitudeRef",
        "GPSAltitude", "GPSAltitudeRef",
        "GPSTimeStamp", "GPSDateStamp",
        "GPSProcessingMethod", "GPSAreaInformation",
    }

    gps_data = {k: v for k, v in all_meta.items() if k in gps_keys}

    return gps_data if gps_data else None


def set_gps_metadata(
    image_path: Union[str, Path],
    latitude: float,
    longitude: float,
    create_backup: bool = False,
) -> bool:
    """
    Write GPS coordinates to an image file's EXIF metadata.

    Args:
        image_path: Path to image file.
        latitude: Latitude in decimal degrees.
        longitude: Longitude in decimal degrees.
        create_backup: If True, create a backup file (original_name_original).

    Returns:
        True on success.

    Raises:
        CoordinateConversionError: If coordinates are invalid.
        MetadataWriteError: If writing metadata fails.
    """
    # Validate coordinates by generating tags (will raise if invalid)
    gps_tags = float_to_gps_tags(latitude, longitude)

    path = Path(image_path)
    if not path.is_file():
        raise MetadataWriteError(f"File not found: {image_path}")

    # Build exiftool arguments
    args = ["-overwrite_original" if not create_backup else ""]
    args = [a for a in args if a]  # Remove empty strings

    # Add GPS tags
    for tag, value in gps_tags.items():
        args.append(f"-{tag}={value}")

    args.append(str(path))

    exiftool_path = _get_exiftool_path()
    cmd = [exiftool_path] + args

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        # Success: exiftool returns 0 and prints "1 image files updated"
        return True
    except subprocess.CalledProcessError as exc:
        raise MetadataWriteError(
            f"ExifTool failed to write metadata: {exc.stderr.strip()}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MetadataWriteError("ExifTool timed out after 30 seconds") from exc
