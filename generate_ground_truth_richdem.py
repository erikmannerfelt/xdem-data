import os
from typing import Union, List, Any
from geoutils.raster import RasterType

import numpy as np
import geoutils as gu
import richdem as rd

# xDEM attribute name : RichDEM attribute name, degrees
attributes_richdem = {
            "slope_Horn": ("slope", True),
            "aspect_Horn": ("aspect", True),
            "hillshade_Horn": "hillshade",
            "curvature": "curvature",
            "profile_curvature": "profile_curvature",
            "planform_curvature": ("planform_curvature", True),
        }

def raster_to_rda(rst: RasterType) -> rd.rdarray:
    """
    Convert geoutils.Raster to richDEM rdarray.
    """
    arr = rst.data.filled(rst.nodata).squeeze()
    rda = rd.rdarray(arr, no_data=rst.nodata)
    rda.geotransform = rst.transform.to_gdal()
    return rda


def get_terrainattr_richdem(rst: RasterType, attribute: str = "slope_radians") -> np.ndarray[Any]:
    """
    Derive terrain attribute for DEM opened with geoutils.Raster using RichDEM.
    """
    rda = raster_to_rda(rst)
    terrattr = rd.TerrainAttribute(rda, attrib=attribute)
    terrattr[terrattr == terrattr.no_data] = np.nan
    return np.array(terrattr)


def get_terrain_attribute_richdem(
    dem: RasterType,
    attribute: Union[str, List[str]],
    degrees: bool = True,
    hillshade_altitude: float = 45.0,
    hillshade_azimuth: float = 315.0,
    hillshade_z_factor: float = 1.0,
) -> Union[RasterType, List[RasterType]]:
    """
    Derive one or multiple terrain attributes from a DEM using RichDEM.
    """
    if isinstance(attribute, str):
        attribute = [attribute]

    if not isinstance(dem, gu.Raster):
        raise ValueError("DEM must be a geoutils.Raster object.")

    terrain_attributes = {}

    # Check which products should be made to optimize the processing
    make_aspect = any(attr in attribute for attr in ["aspect", "hillshade"])
    make_slope = any(
        attr in attribute
        for attr in [
            "slope",
            "hillshade",
            "planform_curvature",
            "aspect",
            "profile_curvature",
            "maximum_curvature",
        ]
    )
    make_hillshade = "hillshade" in attribute
    make_curvature = "curvature" in attribute
    make_planform_curvature = "planform_curvature" in attribute or "maximum_curvature" in attribute
    make_profile_curvature = "profile_curvature" in attribute or "maximum_curvature" in attribute

    if make_slope:
        terrain_attributes["slope"] = get_terrainattr_richdem(dem, "slope_radians")

    if make_aspect:
        # The aspect of RichDEM is returned in degrees, we convert to radians to match the others
        terrain_attributes["aspect"] = np.deg2rad(get_terrainattr_richdem(dem, "aspect"))
        # For flat slopes, RichDEM returns a 90° aspect by default, while GDAL return a 180° aspect
        # We stay consistent with GDAL
        slope_tmp = get_terrainattr_richdem(dem, "slope_radians")
        terrain_attributes["aspect"][slope_tmp == 0] = np.pi

    if make_hillshade:
        # If a different z-factor was given, slopemap with exaggerated gradients.
        if hillshade_z_factor != 1.0:
            slopemap = np.arctan(np.tan(terrain_attributes["slope"]) * hillshade_z_factor)
        else:
            slopemap = terrain_attributes["slope"]

        azimuth_rad = np.deg2rad(360 - hillshade_azimuth)
        altitude_rad = np.deg2rad(hillshade_altitude)

        # The operation below yielded the closest hillshade to GDAL (multiplying by 255 did not work)
        # As 0 is generally no data for this uint8, we add 1 and then 0.5 for the rounding to occur between
        # 1 and 255
        terrain_attributes["hillshade"] = np.clip(
            1.5
            + 254
            * (
                np.sin(altitude_rad) * np.cos(slopemap)
                + np.cos(altitude_rad) * np.sin(slopemap) * np.sin(azimuth_rad - terrain_attributes["aspect"])
            ),
            0,
            255,
        ).astype("float32")

    if make_curvature:
        terrain_attributes["curvature"] = get_terrainattr_richdem(dem, "curvature")

    if make_planform_curvature:
        terrain_attributes["planform_curvature"] = get_terrainattr_richdem(dem, "planform_curvature")

    if make_profile_curvature:
        terrain_attributes["profile_curvature"] = get_terrainattr_richdem(dem, "profile_curvature")

    # Convert the unit if wanted.
    if degrees:
        for attr in ["slope", "aspect"]:
            if attr not in terrain_attributes:
                continue
            terrain_attributes[attr] = np.rad2deg(terrain_attributes[attr])

    output_attributes = [terrain_attributes[key].reshape(dem.shape) for key in attribute]

    if isinstance(dem, gu.Raster):
        output_attributes = [
            gu.Raster.from_array(attr, transform=dem.transform, crs=dem.crs, nodata=-99999)
            for attr in output_attributes
        ]

    return output_attributes if len(output_attributes) > 1 else output_attributes[0]


def generate_ground_truth_richdem(dem: gu.Raster,
                                  attribute_dict: dict[str, str | tuple[str, bool]],
                                  save_dir: str) -> None:
    """
    Generate and save ground truth terrain attributes using RichDEM.

    :param dem: DEM as a geoutils.Raster object.
    :param attribute_dict: dictionary of richdem terrain attributes.
    :param save_dir: Directory where the ground truth data will be saved.
    """
    # Create output directory if needed
    os.makedirs(save_dir, exist_ok=True)

    for attribute, value in attribute_dict.items():
        # Generate the terrain attribute using RichDEM
        if isinstance(value, tuple):
            terrain_attribute = get_terrain_attribute_richdem(dem, attribute=value[0], degrees=value[1])
        else:
            terrain_attribute = get_terrain_attribute_richdem(dem, attribute=value)

        # Save the generated attribute as a .npy file
        save_path = os.path.join(save_dir, f"{attribute}.tif")
        terrain_attribute.save(save_path)


if __name__ == "__main__":
    filepath = "data/Longyearbyen/DEM_2009_ref.tif"
    output_dir = "test_data/richdem"
    dem = gu.Raster(filepath, load_data=True)
    generate_ground_truth_richdem(dem=dem, attribute_dict=attributes_richdem, save_dir=output_dir)
