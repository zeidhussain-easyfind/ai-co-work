# efps-geotag-manager

Sets or updates GPS coordinates on image files using ExifTool.

## Overview

This module provides in-place GPS metadata management for image files. It reads and writes
GPS coordinates (latitude/longitude) directly on images without re-encoding pixel data or
corrupting non-GPS metadata fields (EXIF, IPTC, XMP, MakerNotes, thumbnails, color profiles).

**Data Safety Guarantees:**
- Only GPS tags are modified; all other metadata is 100% untouched
- No pixel re-encoding or recompression occurs
- In-place updates via PyExifTool's native tag writing
- Optional backup creation before modification

## Prerequisites

- Python 3.9+
- [ExifTool](https://exiftool.org/) binary installed and available in system PATH
  - macOS: `brew install exiftool`
  - Linux (Debian/Ubuntu): `sudo apt install libimage-exiftool-perl`
  - Windows: download from https://exiftool.org/

## Installation

```bash
pip install -r requirements.txt
```

## Environment Variables

Copy `.env.example` to `.env` and fill in real values.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `IMAGE_DIR` | Yes | `./target_images` | Directory containing images to process |
| `DEFAULT_LATITUDE` | Yes | — | GPS latitude in decimal degrees (-90 to 90). Positive = North, Negative = South |
| `DEFAULT_LONGITUDE` | Yes | — | GPS longitude in decimal degrees (-180 to 180). Positive = East, Negative = West |
| `BACKUP` | No | `false` | If `true`, creates backup files (e.g., `image.jpg_original`) before modifying |

## Supported Image Formats

`.jpg`, `.jpeg`, `.tiff`, `.tif`, `.png`, `.heic`, `.heif`, `.raw`, `.cr2`, `.nef`, `.arw`, `.dng`

## Usage

### As a Python Module

```python
from geotag_manager import set_gps_metadata, process_directory, verify_exiftool

# Verify exiftool is available
verify_exiftool()

# Update a single image (latitude, longitude in decimal degrees)
set_gps_metadata(
    file_path="/path/to/image.jpg",
    latitude=37.7749,
    longitude=-122.4194,
    create_backup=True
)

# Process all images in a directory
results = process_directory(
    directory="./target_images",
    latitude=37.7749,
    longitude=-122.4194,
    create_backup=False
)
print(results)
```

### As a CLI Script

```bash
# Set GPS on a single image
python geotag_manager.py --file photo.jpg --lat 37.7749 --lon -122.4194

# Process all images in a directory
python geotag_manager.py --dir ./target_images --lat 37.7749 --lon -122.4194

# With backup enabled
python geotag_manager.py --dir ./target_images --lat 37.7749 --lon -122.4194 --backup
```

## Architecture

```
modules/geotag-manager/
├── README.md                  # This file
├── .env.example               # Environment variable template
├── requirements.txt           # Python dependencies
├── geotag_manager.py          # Core module — GPS operations
├── target_images/             # Directory for images to process
│   └── .gitkeep
└── tests/
    ├── __init__.py
    ├── conftest.py            # Test configuration and path setup
    └── test_geotag_manager.py # Unit tests for conversion and scanning
```

## GPS Coordinate Format

The module accepts standard decimal degree coordinates and converts them to EXIF-compatible DMS (Degrees/Minutes/Seconds) format internally.

| Input | Direction | EXIF Output |
|-------|-----------|-------------|
| `37.7749` | Latitude | `37 46 29.6400` + `N` |
| `-122.4194` | Longitude | `122 25 10.0800` + `W` |
| `-33.8688` | Latitude | `33 52 7.6800` + `S` |
| `151.2093` | Longitude | `151 12 33.4800` + `E` |

## Testing

```bash
cd modules/geotag-manager
pip install -r requirements.txt
pip install pytest
pytest tests/ -v
```

## IAM Permissions

Not applicable — this module runs locally and does not interact with AWS services.
