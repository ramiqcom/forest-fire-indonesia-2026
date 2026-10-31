from concurrent.futures import ThreadPoolExecutor
from logging import INFO, basicConfig, getLogger
from pathlib import Path
from shutil import which
from subprocess import check_call

from dotenv import load_dotenv
from s4g.composite import generate_s1_composite

load_dotenv()

basicConfig(
    level=INFO,
    format="%(asctime)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = getLogger(__name__)

ROI_PATH = Path("input/palangka_raya.geojson")
AOI_NAME = ROI_PATH.stem
OUTPUT_LOCAL = Path("output")
CLOUD_PREFIX = "gs://gee-ramiqcom-s4g-bucket/forest_fire_indonesian_2026/s1"
RESOLUTION = 30
SOURCE = "earthdata"
ORBIT = "ascending"

DATES = [
    dict(name="2026-06", start="2026-06-01", end="2026-06-30"),
    dict(name="2026-10", start="2026-10-01", end="2026-10-31"),
]


def run_s1(date: dict):
    name = f"{AOI_NAME}_{date['name']}"
    output_path = OUTPUT_LOCAL / f"{name}.tif"

    logger.info(f"Run S1 {name}")
    generate_s1_composite(
        str(output_path),
        str(ROI_PATH),
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

    with ThreadPoolExecutor(len(DATES)) as executor:
        jobs = {date["name"]: executor.submit(run_s1, date) for date in DATES}

    failed = []
    for name, job in jobs.items():
        try:
            job.result()
        except Exception as e:
            logger.error(f"Error {name}: {e}")
            failed.append(name)

    if failed:
        raise SystemExit(f"Failed: {', '.join(failed)}")
