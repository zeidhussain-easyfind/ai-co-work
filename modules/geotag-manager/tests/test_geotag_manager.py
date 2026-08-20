"""
Tests for efps-geotag-manager
==============================

Unit tests for GPS coordinate conversion and directory scanning.
Integration tests (marked with ``@pytest.mark.integration``) require
the exiftool binary to be installed on the system.

Run all tests:
    pytest tests/ -v

Run unit tests only:
    pytest tests/ -v -m "not integration"
"""

import os
import sys
import shutil
import pytest

from geotag_manager import (
    GeotagError,
    ExifToolNotAvailableError,
    CoordinateConversionError,
    MetadataReadError,
    MetadataWriteError,
    SUPPORTED_EXTENSIONS,
    decimal_to_dms,
    float_to_gps_tags,
    find_images,
    verify_exiftool,
)

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------
integration = pytest.mark.integration


# ---------------------------------------------------------------------------
# Unit Tests — decimal_to_dms
# ---------------------------------------------------------------------------
class TestDecimalToDms:
    """Unit tests for decimal-to-DMS coordinate conversion."""

    def test_positive_latitude(self) -> None:
        """San Francisco latitude converts correctly."""
        degrees, minutes, seconds = decimal_to_dms(37.7749)
        assert degrees == 37
        assert minutes == 46
        assert abs(seconds - 29.64) < 0.01

    def test_negative_latitude(self) -> None:
        """Sydney latitude (negative) converts correctly."""
        degrees, minutes, seconds = decimal_to_dms(-33.8688)
        assert degrees == 33
        assert minutes == 52
        assert abs(seconds - 7.68) < 0.01

    def test_positive_longitude(self) -> None:
        """Tokyo longitude converts correctly."""
        degrees, minutes, seconds = decimal_to_dms(139.6917)
        assert degrees == 139
        assert minutes == 41
        assert abs(seconds - 30.12) < 0.01

    def test_negative_longitude(self) -> None:
        """San Francisco longitude (negative) converts correctly."""
        degrees, minutes, seconds = decimal_to_dms(-122.4194)
        assert degrees == 122
        assert minutes == 25
        assert abs(seconds - 10.08) < 0.01

    def test_zero(self) -> None:
        """Zero degrees converts to (0, 0, 0.0)."""
        degrees, minutes, seconds = decimal_to_dms(0.0)
        assert degrees == 0
        assert minutes == 0
        assert abs(seconds - 0.0) < 0.001

    def test_integer_input(self) -> None:
        """Integer input is handled gracefully."""
        degrees, minutes, seconds = decimal_to_dms(45)
        assert degrees == 45
        assert minutes == 0
        assert abs(seconds - 0.0) < 0.001

    def test_string_input_raises(self) -> None:
        """Non-numeric string raises CoordinateConversionError."""
        with pytest.raises(CoordinateConversionError, match="Cannot convert"):
            decimal_to_dms("not_a_number")

    def test_none_input_raises(self) -> None:
        """None input raises CoordinateConversionError."""
        with pytest.raises(CoordinateConversionError, match="Cannot convert"):
            decimal_to_dms(None)


# ---------------------------------------------------------------------------
# Unit Tests — float_to_gps_tags
# ---------------------------------------------------------------------------
class TestFloatToGpsTags:
    """Unit tests for float-to-EXIF GPS tag conversion."""

    def test_northeast(self) -> None:
        """Positive lat + positive lon = N + E."""
        tags = float_to_gps_tags(37.7749, 122.4194)
        assert tags["GPSLatitudeRef"] == "N"
        assert tags["GPSLongitudeRef"] == "E"

    def test_northwest(self) -> None:
        """Positive lat + negative lon = N + W."""
        tags = float_to_gps_tags(37.7749, -122.4194)
        assert tags["GPSLatitudeRef"] == "N"
        assert tags["GPSLongitudeRef"] == "W"

    def test_southeast(self) -> None:
        """Negative lat + positive lon = S + E."""
        tags = float_to_gps_tags(-33.8688, 151.2093)
        assert tags["GPSLatitudeRef"] == "S"
        assert tags["GPSLongitudeRef"] == "E"

    def test_southwest(self) -> None:
        """Negative lat + negative lon = S + W."""
        tags = float_to_gps_tags(-33.8688, -122.4194)
        assert tags["GPSLatitudeRef"] == "S"
        assert tags["GPSLongitudeRef"] == "W"

    def test_equator_prime_meridian(self) -> None:
        """Zero coordinates default to N and E."""
        tags = float_to_gps_tags(0.0, 0.0)
        assert tags["GPSLatitudeRef"] == "N"
        assert tags["GPSLongitudeRef"] == "E"
        assert "GPSLatitude" in tags
        assert "GPSLongitude" in tags

    def test_tag_count(self) -> None:
        """Exactly four GPS tags are produced."""
        tags = float_to_gps_tags(37.7749, -122.4194)
        assert len(tags) == 4

    def test_tag_keys(self) -> None:
        """All expected tag keys are present."""
        tags = float_to_gps_tags(37.7749, -122.4194)
        expected_keys = {
            "GPSLatitude", "GPSLatitudeRef",
            "GPSLongitude", "GPSLongitudeRef",
        }
        assert set(tags.keys()) == expected_keys

    def test_dms_format_contains_spaces(self) -> None:
        """DMS strings use space-separated DD MM SS.ss format."""
        tags = float_to_gps_tags(37.7749, -122.4194)
        assert " " in tags["GPSLatitude"]
        assert " " in tags["GPSLongitude"]

    def test_latitude_out_of_range_high(self) -> None:
        """Latitude > 90 raises CoordinateConversionError."""
        with pytest.raises(CoordinateConversionError, match="out of valid range"):
            float_to_gps_tags(91.0, 0.0)

    def test_latitude_out_of_range_low(self) -> None:
        """Latitude < -90 raises CoordinateConversionError."""
        with pytest.raises(CoordinateConversionError, match="out of valid range"):
            float_to_gps_tags(-91.0, 0.0)

    def test_longitude_out_of_range_high(self) -> None:
        """Longitude > 180 raises CoordinateConversionError."""
        with pytest.raises(CoordinateConversionError, match="out of valid range"):
            float_to_gps_tags(0.0, 181.0)

    def test_longitude_out_of_range_low(self) -> None:
        """Longitude < -180 raises CoordinateConversionError."""
        with pytest.raises(CoordinateConversionError, match="out of valid range"):
            float_to_gps_tags(0.0, -181.0)

    def test_boundary_north_pole(self) -> None:
        """Latitude 90.0 (North Pole) is accepted."""
        tags = float_to_gps_tags(90.0, 0.0)
        assert tags["GPSLatitudeRef"] == "N"

    def test_boundary_south_pole(self) -> None:
        """Latitude -90.0 (South Pole) is accepted."""
        tags = float_to_gps_tags(-90.0, 0.0)
        assert tags["GPSLatitudeRef"] == "S"

    def test_boundary_date_line_east(self) -> None:
        """Longitude 180.0 is accepted."""
        tags = float_to_gps_tags(0.0, 180.0)
        assert tags["GPSLongitudeRef"] == "E"

    def test_boundary_date_line_west(self) -> None:
        """Longitude -180.0 is accepted."""
        tags = float_to_gps_tags(0.0, -180.0)
        assert tags["GPSLongitudeRef"] == "W"


# ---------------------------------------------------------------------------
# Unit Tests — find_images
# ---------------------------------------------------------------------------
class TestFindImages:
    """Unit tests for directory image scanning."""

    def test_nonexistent_directory(self) -> None:
        """Scanning a non-existent directory raises GeotagError."""
        with pytest.raises(GeotagError, match="does not exist"):
            find_images("/nonexistent/path/to/nowhere")

    def test_file_instead_of_directory(self, tmp_path: object) -> None:
        """Passing a file path raises GeotagError."""
        test_file = tmp_path / "not_a_dir.txt"  # type: ignore[operator]
        test_file.write_text("test content")
        with pytest.raises(GeotagError, match="not a directory"):
            find_images(str(test_file))

    def test_empty_directory(self, tmp_path: object) -> None:
        """Empty directory returns an empty list."""
        images = find_images(str(tmp_path))
        assert images == []

    def test_finds_all_supported_formats(self, tmp_path: object) -> None:
        """All supported extensions are detected."""
        for ext in [".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".dng"]:
            (tmp_path / f"photo{ext}").touch()  # type: ignore[operator]
        # Create a non-image file that should be ignored
        (tmp_path / "readme.txt").touch()  # type: ignore[operator]
        (tmp_path / "script.py").touch()  # type: ignore[operator]

        images = find_images(str(tmp_path))
        assert len(images) == 7

    def test_returns_sorted_paths(self, tmp_path: object) -> None:
        """Returned paths are sorted alphabetically."""
        (tmp_path / "zebra.jpg").touch()  # type: ignore[operator]
        (tmp_path / "alpha.png").touch()  # type: ignore[operator]
        (tmp_path / "middle.tiff").touch()  # type: ignore[operator]

        images = find_images(str(tmp_path))
        basenames = [os.path.basename(p) for p in images]
        assert basenames == sorted(basenames)

    def test_ignores_subdirectories(self, tmp_path: object) -> None:
        """Subdirectories are not scanned recursively."""
        (tmp_path / "top.jpg").touch()  # type: ignore[operator]
        sub_dir = tmp_path / "subdir"  # type: ignore[operator]
        sub_dir.mkdir()
        (sub_dir / "nested.jpg").touch()

        images = find_images(str(tmp_path))
        assert len(images) == 1
        assert os.path.basename(images[0]) == "top.jpg"

    def test_returns_absolute_paths(self, tmp_path: object) -> None:
        """Returned paths are absolute."""
        (tmp_path / "image.jpg").touch()  # type: ignore[operator]
        images = find_images(str(tmp_path))
        assert os.path.isabs(images[0])

    def test_case_insensitive_extensions(self, tmp_path: object) -> None:
        """Extensions are matched case-insensitively."""
        (tmp_path / "photo.JPG").touch()  # type: ignore[operator]
        (tmp_path / "photo.Jpg").touch()  # type: ignore[operator]

        images = find_images(str(tmp_path))
        assert len(images) == 2


# ---------------------------------------------------------------------------
# Unit Tests — SUPPORTED_EXTENSIONS
# ---------------------------------------------------------------------------
class TestSupportedExtensions:
    """Verify the set of supported file extensions."""

    def test_common_formats_present(self) -> None:
        """All common image formats are in the supported set."""
        required = {".jpg", ".jpeg", ".png", ".tiff", ".tif"}
        assert required.issubset(SUPPORTED_EXTENSIONS)

    def test_raw_formats_present(self) -> None:
        """RAW camera formats are in the supported set."""
        raw_formats = {".cr2", ".nef", ".arw", ".dng"}
        assert raw_formats.issubset(SUPPORTED_EXTENSIONS)

    def test_mobile_formats_present(self) -> None:
        """Mobile formats (HEIC) are in the supported set."""
        assert ".heic" in SUPPORTED_EXTENSIONS
        assert ".heif" in SUPPORTED_EXTENSIONS

    def test_is_set_type(self) -> None:
        """SUPPORTED_EXTENSIONS is a set for O(1) lookup."""
        assert isinstance(SUPPORTED_EXTENSIONS, set)


# ---------------------------------------------------------------------------
# Integration Tests — require exiftool binary
# ---------------------------------------------------------------------------
def _has_exiftool() -> bool:
    """Check if exiftool is available on this system."""
    return shutil.which("exiftool") is not None


@integration
class TestExifToolVerification:
    """Integration tests for exiftool binary verification."""

    @pytest.mark.skipif(not _has_exiftool(), reason="exiftool not installed")
    def test_verify_exiftool_returns_path(self) -> None:
        """verify_exiftool returns a valid path string."""
        path = verify_exiftool()
        assert isinstance(path, str)
        assert len(path) > 0
        assert os.path.isfile(path)


@integration
class TestCoordinateRoundTrip:
    """Integration tests that verify GPS data can be written and read back."""

    @pytest.mark.skipif(not _has_exiftool(), reason="exiftool not installed")
    def test_write_and_read_gps_jpeg(self, tmp_path: object) -> None:
        """Write GPS to a JPEG and read it back correctly."""
        from geotag_manager import set_gps_metadata, get_gps_metadata, get_all_metadata

        # Create a minimal JPEG file using PIL if available, otherwise skip
        try:
            from PIL import Image
            img_path = str(tmp_path / "test.jpg")  # type: ignore[operator]
            img = Image.new("RGB", (100, 100), color=(255, 0, 0))
            img.save(img_path, "JPEG")
        except ImportError:
            pytest.skip("Pillow not installed — cannot create test JPEG")

        # Record pre-existing metadata
        pre_metadata = get_all_metadata(img_path)

        # Write GPS coordinates
        lat, lon = 37.7749, -122.4194
        result = set_gps_metadata(img_path, lat, lon, create_backup=False)
        assert result is True

        # Read GPS back
        gps = get_gps_metadata(img_path)
        assert gps is not None
        assert "GPSLatitude" in gps
        assert "GPSLatitudeRef" in gps
        assert "GPSLongitude" in gps
        assert "GPSLongitudeRef" in gps
        assert gps["GPSLatitudeRef"] == "N"
        assert gps["GPSLongitudeRef"] == "W"

    @pytest.mark.skipif(not _has_exiftool(), reason="exiftool not installed")
    def test_non_gps_metadata_preserved(self, tmp_path: object) -> None:
        """Non-GPS metadata remains identical after GPS update."""
        from geotag_manager import set_gps_metadata, get_all_metadata

        try:
            from PIL import Image
            img_path = str(tmp_path / "test_preserve.jpg")  # type: ignore[operator]
            img = Image.new("RGB", (100, 100), color=(0, 128, 255))
            img.save(img_path, "JPEG")
        except ImportError:
            pytest.skip("Pillow not installed — cannot create test JPEG")

        # Read ALL metadata before GPS update
        pre_metadata = get_all_metadata(img_path)

        # Write GPS coordinates
        set_gps_metadata(img_path, -33.8688, 151.2093, create_backup=False)

        # Read ALL metadata after GPS update
        post_metadata = get_all_metadata(img_path)

        # Verify non-GPS tags are unchanged
        gps_keys = {
            "GPSLatitude", "GPSLatitudeRef",
            "GPSLongitude", "GPSLongitudeRef",
            "GPSAltitude", "GPSAltitudeRef",
        }

        for key, value in pre_metadata.items():
            if key in gps_keys:
                continue  # GPS tags are expected to change
            assert key in post_metadata, f"Metadata key '{key}' was lost after GPS update"
            assert post_metadata[key] == value, (
                f"Metadata key '{key}' changed from '{value}' "
                f"to '{post_metadata[key]}' after GPS update"
            )
