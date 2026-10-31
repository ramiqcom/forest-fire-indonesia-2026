from concurrent.futures import ThreadPoolExecutor
from logging import INFO, basicConfig, getLogger
from pathlib import Path
from shutil import which
from subprocess import DEVNULL, CalledProcessError, check_call, check_output

from dotenv import load_dotenv
from s4g.composite import generate_opera_surface_water_s1, generate_s1_composite

load_dotenv()

basicConfig(
    level=INFO,
    format="%(asctime)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = getLogger(__name__)

ROI_PATHS = [
    Path("input/palangka_raya.geojson"),
    Path("input/sebangau.geojson"),
    Path("input/kundangan.geojson"),
]
OUTPUT_LOCAL = Path("output")
CLOUD_PREFIX = "gs://gee-ramiqcom-s4g-bucket/forest_fire_indonesian_2026"
RESOLUTION = 30
SOURCE = "earthdata"
ORBIT = "both"

# Product name, also the bucket folder, and the function with its extra arguments
PRODUCTS = {
    "s1": (generate_s1_composite, dict(source=SOURCE, orbit=ORBIT)),
    "surface_water_s1": (generate_opera_surface_water_s1, dict()),
}

DATES = [
    dict(name="2026-06", start="2026-06-01", end="2026-06-30"),
    dict(name="2026-10", start="2026-10-01", end="2026-10-31"),
]


def list_done(product: str) -> set[str]:
    try:
        paths = check_output(
            [which("gcloud"), "storage", "ls", f"{CLOUD_PREFIX}/{product}/"],
            text=True,
            stderr=DEVNULL,
        )
    except CalledProcessError:
        # Prefix does not exist yet
        return set()
    return {Path(path).stem for path in paths.split()}


def run(product: str, roi_path: Path, date: dict):
    name = f"{roi_path.stem}_{date['name']}"
    output_path = OUTPUT_LOCAL / f"{product}_{name}.tif"
    generate, kwargs = PRODUCTS[product]

    logger.info(f"Run {product} {name}")
    generate(
        str(output_path),
        str(roi_path),
        (date["start"], date["end"]),
        resolution=RESOLUTION,
        **kwargs,
    )

    logger.info(f"Upload {product} {name}")
    check_call(
        [which("gcloud"), "storage", "cp", str(output_path), f"{CLOUD_PREFIX}/{product}/{name}.tif"]
    )

    output_path.unlink()


if __name__ == "__main__":
    OUTPUT_LOCAL.mkdir(exist_ok=True)

    todo = []
    for product in PRODUCTS:
        done = list_done(product)
        for roi_path in ROI_PATHS:
            for date in DATES:
                name = f"{roi_path.stem}_{date['name']}"
                if name in done:
                    logger.info(f"Skip {product} {name}, already in {CLOUD_PREFIX}/{product}")
                else:
                    todo.append((product, roi_path, date))

    jobs = {}
    if todo:
        with ThreadPoolExecutor(len(todo)) as executor:
            jobs = {
                f"{product} {roi_path.stem}_{date['name']}": executor.submit(
                    run, product, roi_path, date
                )
                for product, roi_path, date in todo
            }

    failed = []
    for name, job in jobs.items():
        try:
            job.result()
        except Exception as e:
            logger.error(f"Error {name}: {e}")
            failed.append(name)

    if failed:
        raise SystemExit(f"Failed: {', '.join(failed)}")
