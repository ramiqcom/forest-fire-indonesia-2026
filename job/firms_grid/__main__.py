from logging import INFO, basicConfig, getLogger
from math import ceil, floor
from pathlib import Path
from shutil import which
from subprocess import DEVNULL, CalledProcessError, call, check_call, check_output

import geopandas as gpd
from dotenv import load_dotenv

from forest_fire.aoi import REGIONS, read_provinces

load_dotenv()

basicConfig(
    level=INFO,
    format="%(asctime)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = getLogger(__name__)

OUTPUT_LOCAL = Path("output/firms_grid")
CLOUD_PREFIX = "gs://gee-ramiqcom-s4g-bucket/forest_fire_indonesian_2026"
INPUT_PRODUCT = "firms"
PRODUCT = "firms_grid"
WORLDCOVER_PRODUCT = "worldcover"
DATE_NAME = "2026-08_2026-10"

CRS = "EPSG:4326"
# Around 1 km at the equator, cells are narrower away from it (about 0.95 km at 18° S)
RESOLUTION = 0.009
# Count the fire points within half a cell from the cell centre
RADIUS = RESOLUTION / 2
NODATA = 65535
# WorldCover class of permanent water bodies
WORLDCOVER_WATER = 80
COMPRESS = "--co=COMPRESS=ZSTD"


def list_done() -> set[str]:
    try:
        paths = check_output(
            [which("gcloud"), "storage", "ls", f"{CLOUD_PREFIX}/{PRODUCT}/"],
            text=True,
            stderr=DEVNULL,
        )
    except CalledProcessError:
        # Prefix does not exist yet
        return set()
    return {Path(path).stem for path in paths.split()}


def get_extent(aoi: gpd.GeoDataFrame) -> list[str]:
    xmin, ymin, xmax, ymax = aoi.to_crs(CRS).total_bounds
    # Snap to the resolution so the cells line up
    return [
        f"{floor(xmin / RESOLUTION) * RESOLUTION:.4f}",
        f"{floor(ymin / RESOLUTION) * RESOLUTION:.4f}",
        f"{ceil(xmax / RESOLUTION) * RESOLUTION:.4f}",
        f"{ceil(ymax / RESOLUTION) * RESOLUTION:.4f}",
    ]


def run(region: str):
    name = f"{region}_{DATE_NAME}"
    folder = OUTPUT_LOCAL / region
    folder.mkdir(parents=True, exist_ok=True)

    aoi = read_provinces(region)
    extent = ",".join(get_extent(aoi))
    roi_path = folder / "roi.fgb"
    aoi.to_file(roi_path, driver="FlatGeobuf")

    # One FIRMS file per province from the firms job
    firms_paths = [f"{CLOUD_PREFIX}/{INPUT_PRODUCT}/{p}_{DATE_NAME}.fgb" for p in aoi.index]

    logger.info(f"Download {INPUT_PRODUCT} data {region}")
    check_call([which("gcloud"), "storage", "cp", *firms_paths, str(folder)])
    local_paths = [str(folder / Path(path).name) for path in firms_paths]

    logger.info(f"Merge fire points {region}")
    merged_path = folder / "firms_merged.fgb"
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

    logger.info(f"Grid fire points {region}")
    grid_path = folder / "firms_grid.tif"
    check_call(
        [
            which("gdal"), "vector", "grid", "count",
            f"--extent={extent}",
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

    # WorldCover from job/worldcover, generated once per region
    logger.info(f"Download WorldCover {region}")
    worldcover_path = folder / "worldcover.tif"
    worldcover_url = f"{CLOUD_PREFIX}/{WORLDCOVER_PRODUCT}/{region}.tif"
    if call([which("gcloud"), "storage", "cp", worldcover_url, str(worldcover_path)]) != 0:
        raise RuntimeError(f"No WorldCover at {worldcover_url}, run job/worldcover first")

    # Same grid as the fire count so both can be combined pixel by pixel
    worldcover_grid_path = folder / "worldcover_grid.tif"
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

    # Region as 1 on the same grid, a cell is inside when its centre is inside,
    # so coastal cells that are mostly sea are left out
    logger.info(f"Rasterize {region}")
    roi_grid_path = folder / "roi_grid.tif"
    check_call(
        [
            which("gdal"), "vector", "rasterize",
            "--burn=1",
            "--init=0",
            "--ot=UInt8",
            f"--extent={extent}",
            f"--resolution={RESOLUTION},{RESOLUTION}",
            COMPRESS,
            "--overwrite",
            str(roi_path),
            str(roi_grid_path),
        ]
    )  # fmt: skip

    logger.info(f"Mask sea and water {region}")
    land_path = folder / "firms_grid_land.tif"
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

    output_path = folder / f"{name}.tif"
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

    logger.info(f"Upload {PRODUCT} {name}")
    check_call(
        [which("gcloud"), "storage", "cp", str(output_path), f"{CLOUD_PREFIX}/{PRODUCT}/{name}.tif"]
    )


if __name__ == "__main__":
    done = list_done()

    failed = []
    for region in REGIONS:
        name = f"{region}_{DATE_NAME}"
        if name in done:
            logger.info(f"Skip {PRODUCT} {name}, already in {CLOUD_PREFIX}/{PRODUCT}")
            continue
        try:
            run(region)
        except Exception as e:
            logger.error(f"Error {PRODUCT} {name}: {e}")
            failed.append(name)

    if failed:
        raise SystemExit(f"Failed: {', '.join(failed)}")
