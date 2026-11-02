from os import getenv

from dotenv import load_dotenv

load_dotenv()

FIRMS_MAP_KEY = getenv("FIRMS_MAP_KEY")
FIRMS_API_PREFIX = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{FIRMS_MAP_KEY}"
MAP_KEYS = ["MODIS_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "VIIRS_SNPP_NRT"]
