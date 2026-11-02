from logging import INFO, basicConfig, getLogger
from math import ceil, floor
from pathlib import Path
from shutil import which
from subprocess import check_call, check_output

import geopandas as gpd
from dotenv import load_dotenv
from s4g.composite import generate_worldcover

load_dotenv()

basicConfig(
    level=INFO,
    format="%(asctime)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = getLogger(__name__)

AOI_URL = "https://storage.googleapis.com/gee-ramiqcom-bucket/admin/indonesia_adm_level_1.fgb"
# Kalimantan provinces only
AOI_FILTER = "WADMPR LIKE 'Kalimantan%'"
OUTPUT_LOCAL = Path("output/firms_grid")
CLOUD_PREFIX = "gs://gee-ramiqcom-s4g-bucket/forest_fire_indonesian_2026"
INPUT_PRODUCT = "firms"
PRODUCT = "firms_grid"
NAME = "kalimantan_2026-08_2026-10"

CRS = "EPSG:4326"
# Around 1 km at the equator, Kalimantan is within 5 degrees of it
RESOLUTION = 0.009
# Count the fire points within half a cell from the cell centre
RADIUS = RESOLUTION / 2
NODATA = 65535
# WorldCover class of permanent water bodies
WORLDCOVER_WATER = 80
COMPRESS = "--co=COMPRESS=ZSTD"


def get_extent() -> list[str]:
    aoi = gpd.read_file(f"/vsicurl/{AOI_URL}", where=AOI_FILTER, columns=["WADMPR"])
    xmin, ymin, xmax, ymax = aoi.to_crs(CRS).total_bounds
    # Snap to the resolution so the cells line up
    return [
        f"{floor(xmin / RESOLUTION) * RESOLUTION:.4f}",
        f"{floor(ymin / RESOLUTION) * RESOLUTION:.4f}",
        f"{ceil(xmax / RESOLUTION) * RESOLUTION:.4f}",
        f"{ceil(ymax / RESOLUTION) * RESOLUTION:.4f}",
    ]


if __name__ == "__main__":
    OUTPUT_LOCAL.mkdir(parents=True, exist_ok=True)

    logger.info(f"Download {INPUT_PRODUCT} data")
    firms_paths = check_output(
        [which("gcloud"), "storage", "ls", f"{CLOUD_PREFIX}/{INPUT_PRODUCT}/*.fgb"], text=True
    ).split()
    check_call([which("gcloud"), "storage", "cp", *firms_paths, str(OUTPUT_LOCAL)])
    local_paths = [str(OUTPUT_LOCAL / Path(path).name) for path in firms_paths]

    logger.info("Merge fire points")
    merged_path = OUTPUT_LOCAL / "firms_merged.fgb"
    check_call(
        [
            which("gdal"), "vector", "concat",
            "--mode=single",
            "--output-layer=FIRMS",
            f"--output-crs={CRS}",
            "--overwrite",
            *local_paths,
            str(merged_path),
        ]
    )  # fmt: skip

    logger.info("Grid fire points")
    grid_path = OUTPUT_LOCAL / "firms_grid.tif"
    check_call(
        [
            which("gdal"), "vector", "grid", "count",
            f"--extent={','.join(get_extent())}",
            f"--resolution={RESOLUTION},{RESOLUTION}",
            f"--radius={RADIUS}",
            "--ot=UInt16",
            f"--nodata={NODATA}",
            COMPRESS,
            "--co=TILED=YES",
            "--overwrite",
            str(merged_path),
            str(grid_path),
        ]
    )  # fmt: skip

    logger.info("Generate WorldCover")
    worldcover_path = OUTPUT_LOCAL / "worldcover.tif"
    generate_worldcover(str(worldcover_path), AOI_URL, roi_sql_where=AOI_FILTER, resolution=100)

    # Same grid as the fire count so both can be combined pixel by pixel
    worldcover_grid_path = OUTPUT_LOCAL / "worldcover_grid.tif"
    check_call(
        [
            which("gdal"), "raster", "reproject",
            f"--like={grid_path}",
            "--resampling=mode",
            COMPRESS,
            "--overwrite",
            str(worldcover_path),
            str(worldcover_grid_path),
        ]
    )  # fmt: skip

    # Kalimantan as 1 on the same grid, a cell is inside when its centre is inside,
    # so coastal cells that are mostly sea are left out
    logger.info("Rasterize Kalimantan")
    roi_grid_path = OUTPUT_LOCAL / "roi_grid.tif"
    check_call(
        [
            which("gdal"), "vector", "rasterize",
            f"--where={AOI_FILTER}",
            "--burn=1",
            "--init=0",
            "--ot=UInt8",
            f"--extent={','.join(get_extent())}",
            f"--resolution={RESOLUTION},{RESOLUTION}",
            COMPRESS,
            "--overwrite",
            f"/vsicurl/{AOI_URL}",
            str(roi_grid_path),
        ]
    )  # fmt: skip

    logger.info("Mask sea and water")
    land_path = OUTPUT_LOCAL / "firms_grid_land.tif"
    check_call(
        [
            which("gdal"), "raster", "calc",
            f"--input=A={grid_path}",
            f"--input=B={worldcover_grid_path}",
            f"--input=R={roi_grid_path}",
            f"--calc=R == 1 && B != {WORLDCOVER_WATER} ? A : {NODATA}",
            "--ot=UInt16",
            f"--nodata={NODATA}",
            COMPRESS,
            "--co=TILED=YES",
            "--overwrite",
            str(land_path),
        ]
    )  # fmt: skip

    output_path = OUTPUT_LOCAL / f"{NAME}.tif"
    check_call(
        [
            which("gdal"), "raster", "convert",
            "--of=COG",
            COMPRESS,
            # Statistics and LANCZOS overviews to stretch and view it in a GIS app
            "--co=STATISTICS=YES",
            "--co=RESAMPLING=LANCZOS",
            "--co=OVERVIEW_RESAMPLING=LANCZOS",
            "--overwrite",
            str(land_path),
            str(output_path),
        ]
    )  # fmt: skip

    logger.info(f"Upload {PRODUCT} {NAME}")
    check_call(
        [which("gcloud"), "storage", "cp", str(output_path), f"{CLOUD_PREFIX}/{PRODUCT}/{NAME}.tif"]
    )
