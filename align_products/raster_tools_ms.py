import numpy as np
import rasterio
import rasterio.windows
from rasterio.warp import reproject, Resampling
from rasterio.windows import Window
from rasterio.vrt import WarpedVRT
import rasterio.mask
from rasterio.features import geometry_mask
import fiona
from rasterio.crs import CRS
from osgeo import gdal
import os
import shutil


"""

helper functions for global and local alignment of drone products

"""

def copy_if_missing(src, dst):
    if not os.path.exists(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(src, dst)

def find_product_tiff( missions_main_path, mission_name, product_name):
    mission_year = mission_name.split("_")[2]
    mission_folder = os.path.join(missions_main_path, str(mission_year), mission_name)
    try:
        os.listdir(mission_folder)

    except FileNotFoundError:
        print(f"Mission folder not found: {mission_folder}")
        return None
    
    product_path = os.path.join(missions_main_path, mission_year, mission_name, product_name)

    # find the most recent product file in the folder
    product_files = [f for f in os.listdir(product_path) if f.endswith('.tif')]
    product_files.sort(key=lambda x: os.path.getmtime(os.path.join(product_path, x)), reverse=True)
    
    if not product_files:
        print(f"No tiff files found in: {product_path}")
        return None
    
    return os.path.join(product_path, product_files[0])


def combine_ortho_dsm(ortho_path,dsm_path, output_path):
    with rasterio.open(ortho_path) as src:
        ortho_data = src.read()
        ortho_meta = src.meta.copy()
        ortho_nodata = src.nodata

    with rasterio.open(dsm_path) as src:
        dem_data = src.read(1)
        dem_meta = src.meta
        dem_nodata = src.nodata
        dem_data=np.where(dem_data==dem_meta['nodata'],0,dem_data)
    resampled_dem = np.full((ortho_meta['height'], ortho_meta['width']),
                            ortho_nodata,
                             dtype=ortho_data.dtype)
    reproject(
    dem_data, resampled_dem,
    src_transform=dem_meta['transform'],
    src_crs=dem_meta['crs'],
    dst_transform=ortho_meta['transform'],
    dst_crs=ortho_meta['crs'],
    resampling=Resampling.nearest)
    ortho_data[3,:,:] = resampled_dem
    ortho_meta['count'] = 4
    with rasterio.open(output_path, 'w', **ortho_meta) as dst:
        dst.write(ortho_data)


def sanitize_image_metadata(image_path):
    """
    Strips internal band statistics that cause AROSICS/geoarray metadata mismatch errors.
    """
    # Open in Update mode (gdal.GA_Update) so changes can save
    ds = gdal.Open(image_path, gdal.GA_Update)
    if ds is not None:
        # Clear main dataset level metadata that might hold stale band lists
        ds.SetMetadata(None)
        
        # Loop through each individual band
        for i in range(1, ds.RasterCount + 1):
            band = ds.GetRasterBand(i)
            meta = band.GetMetadata()
            
            if meta:
                # Create a new metadata dictionary excluding any statistics keys
                cleaned_meta = {k: v for k, v in meta.items() if 'STATISTICS' not in k.upper()}
                
                # Clear the old metadata completely first
                band.SetMetadata(None)
                
                # Write back the cleaned metadata dictionary
                band.SetMetadata(cleaned_meta)
                
        ds = None  # Close and flush all changes to the file structure
        print(f"Successfully sanitized metadata for {os.path.basename(image_path)}")



# Deshifts with gdal which uses chunks and doesnt use so much memory
def apply_arosics_gcps(src, dst, local1_info, resample_alg=gdal.GRA_Bilinear):
    gdal.UseExceptions()
    src_ds = gdal.Open(src, gdal.GA_ReadOnly)

    # Attach AROSICS local correction GCPs
    src_ds.SetGCPs(
        local1_info["GCPList"],
        local1_info["reference projection"]
    )

    options = gdal.WarpOptions(
        format="GTiff",
        tps=True,  # Thin Plate Spline interpolation handles local shifts beautifully
        resampleAlg=resample_alg, 
        creationOptions=[
            "COMPRESS=LZW",
            "TILED=YES",
            "BIGTIFF=YES"
        ],
        multithread=True,
        warpMemoryLimit=8192
    )

    gdal.Warp(dst, src_ds, options=options)
    src_ds = None
    

def resample_dsm_to_rgb(rgb_path, dsm_path, output_path):
    crs = CRS.from_epsg(32617)
    # Read RGB metadata only
    with rasterio.open(rgb_path) as rgb:
        rgb_meta = rgb.meta

    # Read DSM
    with rasterio.open(dsm_path) as dsm:
        dsm_data = dsm.read(1)
        dsm_meta = dsm.meta.copy()

        nodata = dsm.nodata
        if nodata is not None:
            dsm_data = np.where(dsm_data == nodata, np.nan, dsm_data)

    # Allocate using DSM dtype
    resampled = np.full(
        (rgb_meta["height"], rgb_meta["width"]),
        np.nan,
        dtype=dsm_data.dtype
    )

    reproject(
        source=dsm_data,
        destination=resampled,
        src_transform=dsm_meta["transform"],
        src_crs=crs,
        dst_transform=rgb_meta["transform"],
        dst_crs=crs,
        resampling=Resampling.nearest,
    )

    out_meta = dsm_meta.copy()
    out_meta.update({
        "height": rgb_meta["height"],
        "width": rgb_meta["width"],
        "transform": rgb_meta["transform"],
        "crs": rgb_meta["crs"],
        "count": 1,
        "dtype": dsm_data.dtype,
        "nodata": np.nan if np.issubdtype(dsm_data.dtype, np.floating) else nodata
    })

    with rasterio.open(output_path, "w", **out_meta) as dst:
        dst.write(resampled, 1)


def split_bands(input_tif, output_tif, bands, block_size=4096):
    with rasterio.open(input_tif) as src:
        profile = src.profile.copy()
        profile.update(
            count=len(bands),
            compress="lzw",
            tiled=True,
            blockxsize=256,
            blockysize=256,
            nodata=0,
            BIGTIFF="YES"
        )

        with rasterio.open(output_tif, "w", **profile) as dst:
            # Copy color interpretation (e.g., Red, Green, Blue, Alpha)
            try:
                dst.colorinterp = tuple(
                    src.colorinterp[b - 1] for b in bands
                )
            except Exception:
                pass

            # Copy band descriptions and units
            for i, band in enumerate(bands, start=1):
                desc = src.descriptions[band - 1]

                if desc is not None:
                    dst.set_band_description(
                        i,
                        desc
                    )
                try:
                    unit = src.units[band - 1]
                    if unit:
                        dst.set_band_unit(i, unit)
                except (AttributeError, IndexError):
                    pass

            # Read and write in blocks (windows) to prevent memory allocation of the entire image
            for row_off in range(0, src.height, block_size):
                for col_off in range(0, src.width, block_size):
                    window = rasterio.windows.Window(
                        col_off, row_off,
                        min(block_size, src.width - col_off),
                        min(block_size, src.height - row_off)
                    )
                    # Read only the selected bands for the current window block
                    data = src.read(bands, window=window)
                    # Write the block to the destination file
                    dst.write(data, window=window)

                    

def crop_raster_tile(input_path, output_path, shapely_polygon, block_size=4096):

    # Normalize to a single Shapely geometry
    if hasattr(shapely_polygon, "geometry"):
        geom = shapely_polygon.geometry.unary_union
    else:
        geom = shapely_polygon

    with rasterio.open(input_path) as src:

        # Get bounding box of the polygon
        bounds = geom.bounds

        # Convert geographic bounds to raster window
        crop_window = rasterio.windows.from_bounds(
            *bounds,
            transform=src.transform
        ).round()

        crop_transform = src.window_transform(crop_window)

        # Determine nodata
        if src.nodata is not None:
            nodata_val = src.nodata
        else:
            nodata_val = 0

        out_meta = src.meta.copy()

        out_meta.update({
            "driver": "GTiff",
            "height": int(crop_window.height),
            "width": int(crop_window.width),
            "transform": crop_transform,
            "nodata": nodata_val,
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
            "compress": "deflate",
            "predictor": 2,
            "BIGTIFF": "YES",
        })


        # -------------------------------------------------------
        # Create the polygon mask ONCE for the whole crop area
        # -------------------------------------------------------
        full_mask = geometry_mask(
            [geom],
            out_shape=(
                int(crop_window.height),
                int(crop_window.width)
            ),
            transform=crop_transform,
            invert=True,
        )


        with rasterio.open(output_path, "w", **out_meta) as dst:
            # Copy band descriptions
            for i, desc in enumerate(src.descriptions, start=1):
                if desc:
                    dst.set_band_description(i, desc)

            # Copy units
            for i, unit in enumerate(src.units, start=1):
                if unit:
                    dst.set_band_unit(i, unit)

            for row_off in range(
                0,
                int(crop_window.height),
                block_size
            ):

                for col_off in range(
                    0,
                    int(crop_window.width),
                    block_size
                ):

                    # Size of current output block
                    width = min(
                        block_size,
                        int(crop_window.width) - col_off
                    )

                    height = min(
                        block_size,
                        int(crop_window.height) - row_off
                    )

                    write_window = Window(
                        col_off,
                        row_off,
                        width,
                        height
                    )

                    # Corresponding source window
                    read_window = Window(
                        crop_window.col_off + col_off,
                        crop_window.row_off + row_off,
                        width,
                        height
                    )


                    # Read raster data
                    data = src.read(window=read_window)

                    # Replace zeros with 1 in all bands except the last one
                    data[:-1][data[:-1] == 0] = 1

                    # Get corresponding mask section
                    mask = full_mask[
                        row_off:row_off + height,
                        col_off:col_off + width
                    ]


                    # Apply polygon mask
                    data = np.where(
                        mask[np.newaxis, :, :],
                        data,
                        nodata_val
                    )


                    dst.write(
                        data,
                        window=write_window
                    )


def sanitize_image_metadata(image_path):
    """
    Strips internal band statistics that cause AROSICS/geoarray metadata mismatch errors.
    """
    # Open in Update mode (gdal.GA_Update) so changes can save
    ds = gdal.Open(image_path, gdal.GA_Update)
    if ds is not None:
        # Clear main dataset level metadata that might hold stale band lists
        ds.SetMetadata(None)
        
        # Loop through each individual band
        for i in range(1, ds.RasterCount + 1):
            band = ds.GetRasterBand(i)
            meta = band.GetMetadata()
            
            if meta:
                # Create a new metadata dictionary excluding any statistics keys
                cleaned_meta = {k: v for k, v in meta.items() if 'STATISTICS' not in k.upper()}
                
                # Clear the old metadata completely first
                band.SetMetadata(None)
                
                # Write back the cleaned metadata dictionary
                band.SetMetadata(cleaned_meta)
                
        ds = None  # Close and flush all changes to the file structure
        print(f"Successfully sanitized metadata for {os.path.basename(image_path)}")