from datetime import datetime, timedelta
from logging import getLogger
from subprocess import check_call
from tempfile import TemporaryDirectory

from .config import FIRMS_API_PREFIX, MAP_KEYS

logger = getLogger(__name__)


def get_firms_alert(
    bbox: tuple[float, float, float, float], date_range: tuple[str, str]
) -> str:
    """Download FIRMS fire alerts for a bounding box and date range.

    Args:
        bbox: Bounding box as ``(min_lon, min_lat, max_lon, max_lat)``.
        date_range: Start and end dates in ``YYYY-MM-DD`` format.

    Returns:
        The path to the downloaded FIRMS CSV file.
    """
    start_date = datetime.strptime(date_range[0], "%Y-%m-%d")
    end_date = datetime.strptime(date_range[1], "%Y-%m-%d")
    if start_date > end_date:
        raise ValueError("date_range start must not be after its end")

    all_results = []
    # The FIRMS API returns the day range starting from the given date
    window_start = start_date
    while window_start <= end_date:
        window_days = min(5, (end_date - window_start).days + 1)
        all_results.extend(
            _get_data_per_days(bbox, window_start.strftime("%Y-%m-%d"), window_days)
        )
        window_start += timedelta(days=window_days)

    folder = TemporaryDirectory(delete=False)
    all_combine = f"{folder.name}/all_combine.fgb"
    check_call(
        f"""gdal vector pipeline \
            ! concat --mode=single --output-layer=FIRMS {" ".join(all_results)} \
            ! make-point --x=longitude --y=latitude --output-crs=EPSG:4326 \
            ! write -f FlatGeobuf {all_combine} \
        """,
        shell=True,
    )

    return all_combine


def _get_data_per_days(
    bbox: tuple[str, str, str, str], start_date: str, difference_in_days: int
) -> list[str]:
    """Download FIRMS alert CSV files for each configured map key.

    Args:
        bbox: Bounding box as ``(min_lon, min_lat, max_lon, max_lat)``.
        start_date: Start date for the requested data in ``YYYY-MM-DD`` format.
        difference_in_days: Number of days to include from ``start_date``.

    Returns:
        Paths to the downloaded CSV files.
    """
    bbox_arg = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"

    folder = TemporaryDirectory(delete=False)

    outputs = []
    for key in MAP_KEYS:
        output = f"{folder.name}/{key}.csv"
        request_url = (
            f"{FIRMS_API_PREFIX}/{key}/{bbox_arg}/{difference_in_days}/{start_date}"
        )
        logger.info(request_url)
        check_call(f"curl -o {output} {request_url}", shell=True)
        outputs.append(output)

    return outputs
