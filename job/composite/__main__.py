from concurrent.futures import ThreadPoolExecutor
from logging import INFO, basicConfig, getLogger
from pathlib import Path
from shutil import which
from subprocess import CalledProcessError, check_call, check_output

from dotenv import load_dotenv
from s4g.composite import generate_s1_composite

load_dotenv()

basicConfig(
    level=INFO,
    format="%(asctime)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = getLogger(__name__)

ROI_PATHS = [Path("input/palangka_raya.geojson"), Path("input/sebangau.geojson")]
OUTPUT_LOCAL = Path("output")
CLOUD_PREFIX = "gs://gee-ramiqcom-s4g-bucket/forest_fire_indonesian_2026/s1"
RESOLUTION = 30
SOURCE = "earthdata"
ORBIT = "both"

DATES = [
    dict(name="2026-06", start="2026-06-01", end="2026-06-30"),
    dict(name="2026-10", start="2026-10-01", end="2026-10-31"),
]


def list_done() -> set[str]:
    try:
        paths = check_output([which("gcloud"), "storage", "ls", f"{CLOUD_PREFIX}/"], text=True)
    except CalledProcessError:
        # Prefix does not exist yet
        return set()
    return {Path(path).stem for path in paths.split()}


def run_s1(roi_path: Path, date: dict):
    name = f"{roi_path.stem}_{date['name']}"
    output_path = OUTPUT_LOCAL / f"{name}.tif"

    logger.info(f"Run S1 {name}")
    generate_s1_composite(
        str(output_path),
        str(roi_path),
        (date["start"], date["end"]),
        resolution=RESOLUTION,
        source=SOURCE,
        orbit=ORBIT,
    )

    logger.info(f"Upload S1 {name}")
    check_call([which("gcloud"), "storage", "cp", str(output_path), f"{CLOUD_PREFIX}/{name}.tif"])

    output_path.unlink()


if __name__ == "__main__":
    OUTPUT_LOCAL.mkdir(exist_ok=True)

    done = list_done()
    todo = [
        (roi_path, date)
        for roi_path in ROI_PATHS
        for date in DATES
        if f"{roi_path.stem}_{date['name']}" not in done
    ]
    for name in sorted(done):
        logger.info(f"Skip S1 {name}, already in {CLOUD_PREFIX}")

    jobs = {}
    if todo:
        with ThreadPoolExecutor(len(todo)) as executor:
            jobs = {
                f"{roi_path.stem}_{date['name']}": executor.submit(run_s1, roi_path, date)
                for roi_path, date in todo
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
