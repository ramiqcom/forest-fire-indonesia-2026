import geopandas as gpd

INDONESIA_ADM1_URL = (
    "https://storage.googleapis.com/gee-ramiqcom-bucket/admin/indonesia_adm_level_1.fgb"
)
# GADM 4.1 states of Brazil, free for non-commercial use only, see https://gadm.org/license.html
GADM_BRAZIL_ADM1_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_BRA_1.json.zip"

# Provinces or states of each region, the source file, the SQL filter and the name field.
# Province names get the prefix in file names, mainland Sumatera leaves out Kepulauan Riau
# and Bangka Belitung
REGIONS = {
    "kalimantan": dict(
        url=INDONESIA_ADM1_URL,
        where="WADMPR LIKE 'Kalimantan%'",
        name_field="WADMPR",
        prefix="",
    ),
    "sumatera": dict(
        url=INDONESIA_ADM1_URL,
        where=(
            "WADMPR LIKE 'Sumatera%' OR WADMPR IN ('Aceh', 'Riau', 'Jambi', 'Bengkulu', 'Lampung')"
        ),
        name_field="WADMPR",
        prefix="",
    ),
    # The 9 states of the Legal Amazon (Amazônia Legal), Maranhão is only partly in it but
    # taken whole, GADM writes the names without spaces
    "legal_amazon": dict(
        url=GADM_BRAZIL_ADM1_URL,
        where=(
            "NAME_1 IN ('Acre', 'Amapá', 'Amazonas', 'Maranhão', 'MatoGrosso', 'Pará', "
            "'Rondônia', 'Roraima', 'Tocantins')"
        ),
        name_field="NAME_1",
        prefix="brazil_",
    ),
}


def gdal_path(url: str) -> str:
    """Return the GDAL path to read ``url``, inside the zip for a zipped file."""
    return f"/vsizip//vsicurl/{url}" if url.endswith(".zip") else f"/vsicurl/{url}"


def read_provinces(region: str) -> gpd.GeoDataFrame:
    """Read the provinces of ``region``, one feature per province in EPSG:4326.

    The index is the province name used in file names, lower case ASCII with ``_`` and the
    region prefix, for example ``kalimantan_barat`` or ``brazil_para``.
    """
    config = REGIONS[region]
    name_field = config["name_field"]
    provinces = gpd.read_file(gdal_path(config["url"]), where=config["where"], columns=[name_field])
    # The source files can store a province as many polygon parts
    provinces = provinces.dissolve(by=name_field).reset_index().to_crs("EPSG:4326")
    # Accents removed so file names stay ASCII, Pará becomes para
    names = (
        provinces[name_field]
        .str.normalize("NFKD")
        .str.encode("ascii", "ignore")
        .str.decode("ascii")
        .str.lower()
        .str.replace(" ", "_")
    )
    provinces.index = (config["prefix"] + names).rename("province")
    return provinces
