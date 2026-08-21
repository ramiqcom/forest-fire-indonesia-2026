from concurrent.futures import ThreadPoolExecutor
from subprocess import check_call, check_output

from ..utils import logger

CPU_PER_PROCESS = 4
OUTPUT_LOCAL = "./output"
OUTPUT_VOLUME = "/usr/src/app/output"
CLOUD_PREFIX = "gs://gee-ramiqcom-s4g-bucket/forest_fire_indonesian_2026_august"
S1_CLOUD_PREFIX = f"{CLOUD_PREFIX}/s1"
RESOLUTION = 10

ADMIN = "gs://gee-ramiqcom-bucket/admin/indonesia_adm_level_1.fgb"
REGION_NAMES = ["Kalimantan Barat"]
DATES = [
    dict(name="after", start="2026-08-20", end="2026-08-20"),
    dict(name="before", start="2026-08-08", end="2026-08-08"),
]


def run_s1(name: str, roi, sql_where: str = "", dates: tuple[str, str] | None = None):
    logger.info("Run S1")

    cmd = f"""docker container run \
                --name s1_{name} \
                --rm \
                --cpus {CPU_PER_PROCESS} \
                -v {OUTPUT_LOCAL}:{OUTPUT_VOLUME} \
                -e S1_ROI_INPUT={roi} \
                -e S1_ROI_SQL_WHERE="{sql_where}" \
                -e S1_START_DATE="{dates[0]}" \
                -e S1_END_DATE="{dates[1]}" \
                -e S1_BANDS='["vv", "vh"]' \
                -e S1_RESOLUTION={RESOLUTION} \
                -e S1_OUTPUT_PREFIX={name} \
                eu.gcr.io/ramadhan-s4g/rs-open-source-docker-base:latest \
                .venv/bin/python -m modules.s1_rtc_composite \
        """

    check_call(cmd, shell=True)

    logger.info("Upload S1 data")
    check_call(
        f"gcloud storage cp {OUTPUT_LOCAL}/{name}*S1*.tif {S1_CLOUD_PREFIX}/",
        shell=True,
    )

    check_call(f"rm {OUTPUT_LOCAL}/{name}*S1*.tif", shell=True)


done_s1 = check_output(
    f"gcloud storage ls {S1_CLOUD_PREFIX}", shell=True, text=True
).split("\n")[:-1]
done_s1 = ["_".join(path.split("/")[-1].split("_")[:3]) for path in done_s1]

with ThreadPoolExecutor(2) as executor:
    jobs = []
    for index in range(len(REGION_NAMES)):
        region_name = REGION_NAMES[index]

        for date_range in DATES:
            name = f"{region_name}_{date_range['name']}"

            date_start = date_range["start"]
            date_end = date_range["end"]
            date_range = (date_start, date_end)

            if name not in done_s1:
                jobs.append(
                    executor.submit(
                        run_s1,
                        name,
                        ADMIN,
                        f"WADMPR == '{region_name}'",
                        date_range,
                    )
                )

    for job in jobs:
        try:
            job.result()
        except Exception as e:
            logger.info(f"Error: {e}")
