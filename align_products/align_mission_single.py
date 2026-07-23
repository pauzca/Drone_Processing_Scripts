import matplotlib.pyplot as plt
import os
import shutil
import rasterio
import numpy as np
import  cv2
from arosics import COREG, COREG_LOCAL, DeShifter
from raster_tools_ms import crop_raster_tile, split_bands, resample_dsm_to_rgb
import geopandas as gpd
from shapely.geometry import box
import pandas as pd
from shapely.geometry import box
from rasterio.warp import reproject, Resampling
from rasterio.merge import merge
import pickle
from rasterio.crs import CRS
import os
import gc


"""

Complete global + local alignemt alignment pipeline based on 
https://github.com/VasquezVicente/ForestLandscapes/blob/main/LandscapeScripts/50ha_aligment_v2.py

Script was modified to:
- Run for multispectral orthomosaic
- Separate the DSM from the RGB in the final product
- Be more memory efficient, although for the 100ha orthomosaic used it needs more than 30GB RAM

"""

os.environ['JOBLIB_TEMP_FOLDER'] = 'D:\\uzcateguipaula\\joblib_tmp'
os.makedirs(os.environ['JOBLIB_TEMP_FOLDER'], exist_ok=True)

orignal_products_path = r"Products\Drone\2024"


align_out_path = r"D:\uzcateguipaula\Aligned"
align_products_path = os.path.join(align_out_path, "Product")
os.makedirs(align_products_path, exist_ok=True)


BCI_50ha_shapefile = os.path.join(align_out_path,"aux_files", "BCI_50ha_big_shape_all.gpkg")
BCI_50ha = gpd.read_file(BCI_50ha_shapefile)
BCI_50ha.to_crs(epsg=32617, inplace=True)
BCI_50ha = BCI_50ha.reset_index(drop=True)



# mission without antenna info or very poor alignment
target_mission = "BCI_50ha_2024_04_03_M3E"
target_ortho = os.path.join(orignal_products_path, target_mission, "Orthophoto", target_mission+"_orthomosaic.tif")
target_dsm = os.path.join(orignal_products_path, target_mission, "DSM", target_mission+"_dsm.tif" )

# mission with PPK coordinate correction and very well aligned with other missions
reference_mission = "BCI_50ha_2024_04_09_M3E"
reference_ortho = os.path.join(orignal_products_path, reference_mission, "Orthophoto", reference_mission + "_orthomosaic.tif") 
reference_dsm = os.path.join(orignal_products_path, reference_mission, "DSM", reference_mission + "_dsm.tif")


#############  DATA PREPARATION  ###########################################################

############ CROP and SPLIT RASTERS ##################################################################

cropped_path = os.path.join(align_out_path, "Product_cropped")

## REFERENCE 
reference_path_cropped_ortho = os.path.join(cropped_path,"Orthomosaic", reference_mission + "_orthomosaic.tiff")
os.makedirs(os.path.dirname(reference_path_cropped_ortho), exist_ok=True)
if not os.path.exists(reference_path_cropped_ortho):
    crop_raster_tile(reference_ortho, reference_path_cropped_ortho, BCI_50ha)
else:
    print(f"Skipping {reference_path_cropped_ortho} because it already exists")

print("Done cropping reference orthomosaic")
reference_rgb_path = os.path.join(
    cropped_path, "RGB",
    reference_mission + "_RGB.tif"
)

reference_ms_path = os.path.join(
    cropped_path, "MS",
    reference_mission + "_MS.tif"
)

if os.path.exists(reference_rgb_path):
    print(f"Reference RGB already processed. Skipping...")
else:
    split_bands(
        reference_path_cropped_ortho,
        reference_rgb_path,
        [1,2,3,8]
    )
print("Reference RGB bands split done")

if os.path.exists(reference_ms_path):
    print(f"Reference MS bands for {reference_path_cropped_ortho} already processed. Skipping...")
else:
    split_bands(
            reference_path_cropped_ortho,
            reference_ms_path,
            [4,5,6,7,8]
        )
print("Reference MS bands split done")


## TARGET PATH 

target_path_cropped_ortho = os.path.join(cropped_path,"Orthomosaic", target_mission + "_orthomosaic.tiff")
os.makedirs(os.path.dirname(target_path_cropped_ortho), exist_ok=True)
if not os.path.exists(target_path_cropped_ortho):
    crop_raster_tile(target_ortho, target_path_cropped_ortho, BCI_50ha)
else:
    print(f"Skipping {target_path_cropped_ortho} because it already exists")

print("Done cropping target orthomosaic")

target_rgb_path = os.path.join(
    cropped_path, "RGB",
    target_mission + "_RGB.tif"
)

target_ms_path = os.path.join(
    cropped_path, "MS",
    target_mission + "_MS.tif"
)

if os.path.exists(target_rgb_path):
    print(f"Target RGB already processed. Skipping...")
else:
    split_bands(
        target_path_cropped_ortho,
        target_rgb_path,
        [1,2,3,8]
    )
print("Target RGB bands split done")

if os.path.exists(target_ms_path):
    print(f"Target MS bands for {target_path_cropped_ortho} already processed. Skipping...")
else:
    split_bands(
            target_path_cropped_ortho,
            target_ms_path,
            [4,5,6,7,8]
        )
    
print("Target MS bands split done")


############ CROP DSM ########################################################################


reference_path_cropped_dsm = os.path.join(cropped_path, "DSM", reference_mission + "_dsm.tiff")
os.makedirs(os.path.dirname(reference_path_cropped_dsm), exist_ok=True)
if not os.path.exists(reference_path_cropped_dsm):
    crop_raster_tile(reference_dsm, reference_path_cropped_dsm, BCI_50ha)
else:
    print(f"Skipping {reference_path_cropped_dsm} because it already exists")

print("Crop reference DSM done")


target_path_cropped_dsm = os.path.join(cropped_path, "DSM", target_mission + "_dsm.tiff")
os.makedirs(os.path.dirname(target_path_cropped_dsm), exist_ok=True)
if not os.path.exists(target_path_cropped_dsm):
    crop_raster_tile(target_dsm, target_path_cropped_dsm, BCI_50ha)
else:
    print(f"Skipping {target_path_cropped_dsm} because it already exists")

print("Crop target DSM done")

## Read reference DEM/DSM
with rasterio.open(reference_path_cropped_dsm) as src:
    dem_data_photo = src.read(src.count) # the last band is the DSM
    dem_meta_photo = src.meta
    dem_meta_photo.update({"dtype": "float32"})
    ref_nd = dem_meta_photo.get('nodata')
    # Exclude both 0 and the official nodata value
    valid_ref_mask = (dem_data_photo != 0)
    if ref_nd is not None:
        valid_ref_mask &= (dem_data_photo != ref_nd)
    ref = np.median(dem_data_photo[valid_ref_mask])
    print("the median of the closest date (excluding nodata) is: ", ref)


reference_dsm_resampled = reference_path_cropped_dsm.replace(".tiff", "_resampled.tiff")
if os.path.exists(reference_dsm_resampled):
    print("Reference dsm already resampled")
else:
    resample_dsm_to_rgb(reference_rgb_path, reference_path_cropped_dsm, reference_dsm_resampled )


## Read resampled reference DEM/DSM
with rasterio.open(reference_dsm_resampled) as src:
    dem_data_photo_resampled = src.read(src.count) # the last band is the DSM
    dem_meta_photo_resampled = src.meta
    dem_meta_photo_resampled.update({"dtype": "float32"})
    # Exclude both 0 and the official nodata value
    valid_ref_mask_resampled = (dem_data_photo_resampled != 0)
    if ref_nd is not None:
        valid_ref_mask_resampled &= (dem_data_photo_resampled != ref_nd)



############# FINISHED DATA PREPARATION ###############################################################################


############### GLOBAL ALIGNMENT ###############################################################################

os.makedirs(os.path.join(align_out_path,'Product_global'), exist_ok=True)

global_path = os.path.join(align_out_path, "Product_global", "Orthophoto", target_mission + "_aligned_global.tif")
coreg_global_info = os.path.join(align_out_path, "Product_global", "COREG_RESULT", target_mission + "_coreg_info.pkl")

if os.path.exists(coreg_global_info):
    print(f"Global alignment for {target_path_cropped_ortho} already processed. Skipping...")
    # load Coreg info
    with open(coreg_global_info, "rb") as f:
        coreg_info = pickle.load(f)
else:
    kwargs2 = { 'path_out': global_path,
                'fmt_out': 'GTIFF',
                'r_b4match': 2,
                's_b4match': 2,
                'max_shift': 200,
                'max_iter': 20,
                'align_grids':True,
                'match_gsd': True,
                'binary_ws': False
                }

    try:
        CR= COREG(reference_path_cropped_ortho, target_path_cropped_ortho, **kwargs2,ws=(2048,2048))
        CR.calculate_spatial_shifts()
        coreg_info = CR.coreg_info

        with open(coreg_global_info, "wb") as f:
            pickle.dump(coreg_info, f)
        print("Global alignment successful")

    except Exception as e:
        print("Global alignment failed")
        print(e)
        raise

gc.collect()

### Apply global alignment to all the bands #####
products_to_align = [
    (target_rgb_path, os.path.join(align_out_path, "Product_global", "RGB", target_mission + "_aligned_global_RGB.tif")),
    (target_ms_path, os.path.join(align_out_path, "Product_global", "MS", target_mission + "_aligned_global_MS.tif")),
    (target_path_cropped_dsm, os.path.join(align_out_path, "Product_global", "DSM", target_mission + "_aligned_global_DSM.tif"))
]

for product, output_path in products_to_align:
    if os.path.exists(output_path):
        print(f"Global alignment for {product} already processed. Skipping...")
    else:
        with rasterio.open(product) as src:
            src_nodata = src.nodata

        DS = DeShifter.DESHIFTER(
            product,
            coreg_info,
            path_out=output_path,
            fmt_out="GTIFF",
            out_crea_options=['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=YES'],
            nodata=src_nodata
        )
        DS.correct_shifts()
        print(f"Done {product}")
        
        # Free DESHIFTER memory 
        del DS
        gc.collect()


## VERTICAL GLOBAL ALIGNMENT ###############################################################################
align_global_dsm_path = os.path.join(align_out_path, "Product_global", "DSM", target_mission + "_aligned_global_DSM.tif")
os.makedirs(os.path.join(align_out_path, "Product_global", "DSM",'Vertical_global'), exist_ok=True)
DSM_BAND = 0  # Assuming the DSM is the first band in the aligned global DSM file

global_vertical_path = os.path.join(align_out_path, "Product_global", "DSM", 'Vertical_global', target_mission + "_aligned_global_DSM.tif")

if os.path.exists(global_vertical_path):
    print("Vertical global alignment already processed. Skipping...")
else:
    with rasterio.open(align_global_dsm_path) as src:
        dem_data_date = src.read()
        tgt_dsm_data = src.meta
        tgt_dsm_data.update({"dtype": "float32"})

        src_nodata = src.nodata  # whatever the file actually says
        print("source nodata value is ", src_nodata)
        if src_nodata is None:
            print("Warning: source DSM has no nodata value set — check gdalinfo")
            src_nodata = -9999.0  # only as a last-resort fallback


        resampled_tgt = np.full(
            (tgt_dsm_data['count'], dem_meta_photo['height'], dem_meta_photo['width']),
            src_nodata,
            dtype=np.float32
        )
        try:
            for band in range(tgt_dsm_data['count']):
                reproject(
                    dem_data_date[band], resampled_tgt[band],
                    src_transform=tgt_dsm_data['transform'],
                    src_crs=tgt_dsm_data['crs'],
                    dst_transform=dem_meta_photo['transform'],
                    dst_crs=dem_meta_photo['crs'],
                    resampling=Resampling.nearest,
                    src_nodata=src_nodata,
                    dst_nodata=src_nodata)
                
            tgt_dsm_data.update({'height': dem_meta_photo['height'],
                    'width': dem_meta_photo['width'],
                    'transform': dem_meta_photo['transform'],
                    'crs': dem_meta_photo['crs']})
            

            dsm_band = resampled_tgt[DSM_BAND]

            # Get target nodata value
            tgt_nd = tgt_dsm_data.get('nodata')
            print("no data value is ", tgt_nd)
        
            # Exclude both 0 and the target nodata value
            valid_tgt_mask = (dsm_band != 0)
            if tgt_nd is not None:
                valid_tgt_mask &= (dsm_band != tgt_nd)

            tgt = np.median(dsm_band[valid_tgt_mask])
            print("the median of the date (excluding nodata) is: ", tgt)

            vertical_offset = ref - tgt

            resampled_tgt[DSM_BAND] = np.where(
                valid_tgt_mask, 
                resampled_tgt[DSM_BAND] + vertical_offset, 
                resampled_tgt[DSM_BAND]
            )
            

            with rasterio.open(global_vertical_path, 'w', **tgt_dsm_data) as dst:
                dst.write(resampled_tgt)
            print("Vertical global alignment done")
            
        except Exception as e:
            print("Vertical global alignment failed")
            print(e)
            raise

##### LOCAL ALIGNMENT ####################################################################################

# Output paths configuration
local_dir = os.path.join(align_out_path, "Product_local")
local2_dir = os.path.join(align_out_path, "Product_local2")

for folder in ["Orthophoto", "RGB", "MS", "DSM", "COREG_RESULT"]:
    os.makedirs(os.path.join(local_dir, folder), exist_ok=True)
    os.makedirs(os.path.join(local2_dir, folder), exist_ok=True)

# File names

# dummy file names, we wont save this because they are too heavy, but we will use them to get the coregistration info
local1_ortho = os.path.join(local_dir, "Orthophoto", target_mission + "_aligned_local.tif")
local2_ortho = os.path.join(local2_dir, "Orthophoto", target_mission + "_aligned_local2.tif")

coreg_local1_info = os.path.join(local_dir, "COREG_RESULT", target_mission + "_coreg_local1_info.pkl")
coreg_local2_info = os.path.join(local2_dir, "COREG_RESULT", target_mission + "_coreg_local2_info.pkl")

# Products to shift mapping
glob_rgb = os.path.join(align_out_path, "Product_global", "RGB", target_mission + "_aligned_global_RGB.tif")
glob_ms  = os.path.join(align_out_path, "Product_global", "MS", target_mission + "_aligned_global_MS.tif")
glob_dsm = os.path.join(align_out_path, "Product_global", "DSM", "Vertical_global", target_mission + "_aligned_global_DSM.tif")

local1_rgb = os.path.join(local_dir, "RGB", target_mission + "_aligned_local_RGB.tif")
local1_ms  = os.path.join(local_dir, "MS", target_mission + "_aligned_local_MS.tif")
local1_dsm = os.path.join(local_dir, "DSM", target_mission + "_aligned_local_DSM.tif")
local2_rgb = os.path.join(local2_dir, "RGB", target_mission + "_aligned_local2_RGB.tif")
local2_ms  = os.path.join(local2_dir, "MS", target_mission + "_aligned_local2_MS.tif")
local2_dsm = os.path.join(local2_dir, "DSM", target_mission + "_aligned_local2_DSM.tif")

# --- Patch geoarray's bool-dtype bug before any AROSICS calls ---
import geoarray.baseclasses as gab
import copyreg
from osgeo import gdal

_orig_reproject = gab.GeoArray.reproject_to_new_grid

def _patched_reproject(self, *args, **kwargs):
    if self.dtype == bool:
        self._arr = self._arr.astype('uint8')
        if isinstance(self.nodata, bool):
            self.nodata = 0
    return _orig_reproject(self, *args, **kwargs)

gab.GeoArray.reproject_to_new_grid = _patched_reproject

# To save and load pickle files with gdal.GCP objects, we need to define custom pickling functions
def _pickle_gcp(gcp):
    return _unpickle_gcp, (gcp.GCPX, gcp.GCPY, gcp.GCPZ,
                            gcp.GCPPixel, gcp.GCPLine, gcp.Info, gcp.Id)

def _unpickle_gcp(x, y, z, pixel, line, info, id_):
    return gdal.GCP(x, y, z, pixel, line, info, id_)

copyreg.pickle(gdal.GCP, _pickle_gcp)

################### 1. LOCAL ALIGNMENT (STAGE 1) ###################
if os.path.exists(coreg_local1_info):
    print("Local alignment Stage 1 parameters exist. Loading...")
    with open(coreg_local1_info, "rb") as f:
        local1_info = pickle.load(f)
else:
    
    kwargs_local = {
        'grid_res': 500,
        'window_size': (256, 256),
        'path_out': local1_ortho,
        'fmt_out': 'GTIFF',
        'min_reliability': 30,
        'r_b4match': 2,
        's_b4match': 2,
        'max_shift': 100,
        'nodata': (0, 0),
        'q': False,
        'match_gsd': False,
        'CPUs': 6
    }
    try:
        
        # Run local coregistration on Orthophotos (Reference vs Globally Aligned Target)
        CRL1 = COREG_LOCAL(reference_rgb_path, glob_rgb, **kwargs_local)
        CRL1.calculate_spatial_shifts()
        #CRL1.correct_shifts()
        local1_info = CRL1.coreg_info

        try:
            with open(coreg_local1_info, "wb") as f:
                pickle.dump(local1_info, f)   # just works, no manual GCP conversion needed
            print("Save coreg info successful")

        except Exception as e:
            print("Failed to save coreg info")
            print(e)

        print("Local alignment Stage 1 horizontal calculation successful.")
    except Exception as e:
        print("Local alignment Stage 1 horizontal calculation failed.")
        raise e
    
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
        warpMemoryLimit=2048
    )

    gdal.Warp(dst, src_ds, options=options)
    src_ds = None


# Resample global DSM to match resolution of RGB and apply local alignment
glob_dsm_resampled = glob_dsm.replace(".tif", "_resampled.tif")
if os.path.exists(glob_dsm_resampled):
    print("DSM already resampled")
else:
    resample_dsm_to_rgb(glob_rgb, glob_dsm, glob_dsm_resampled)



# Apply Stage 1 local shifts to RGB, MS
for src, dst in [(glob_rgb, local1_rgb), (glob_ms, local1_ms), (glob_dsm_resampled, local1_dsm)]:
    if os.path.exists(dst):
        print(f"File {dst} already shifted. Skipping...")
    else:
        # Free memory 
        
        gc.collect()

        print("Shifting file: ", os.path.basename(src))
        apply_arosics_gcps(src, dst, local1_info) #consumes less memory
        print(f"Shift applied to {os.path.basename(src)}")



gc.collect()

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


################### 2. LOCAL ALIGNMENT (STAGE 2 - SMOOTHING) ###################
if os.path.exists(coreg_local2_info):
    print("Local alignment Stage 2 parameters exist. Loading...")
    with open(coreg_local2_info, "rb") as f:
        local2_info = pickle.load(f)
else:
    print("Sanitizing image headers to prevent AROSICS geoarray crash...")
    sanitize_image_metadata(reference_rgb_path)
    sanitize_image_metadata(local1_rgb)

    kwargs_local = {
        'grid_res': 500,
        'window_size': (512, 512),
        'path_out': local2_ortho,
        'fmt_out': 'GTIFF',
        'q': False,
        'min_reliability': 30,
        'r_b4match': 2,
        's_b4match': 2,
        'max_shift': 100,
        'nodata': (0, 0),
        'match_gsd': False,
        'CPUs': 6
    }
    try:
        # Run local coregistration on Reference Ortho vs Stage 1 Locally Aligned Target Ortho
        CRL2 = COREG_LOCAL(reference_rgb_path, local1_rgb, **kwargs_local)
        gc.collect()
        CRL2.calculate_spatial_shifts()
        #CRL2.correct_shifts()
        local2_info = CRL2.coreg_info
        
        # Save shift table to CSV and coreg_info to pickle
        #CRL2.CoRegPoints_table.to_csv(local2_ortho.replace("aligned_local2.tif", "aligned2.csv"))
        try:
            with open(coreg_local2_info, "wb") as f:
                pickle.dump(local2_info, f)   # just works, no manual GCP conversion needed
            print("Save coreg info successful")

        except Exception as e:
            print("Failed to save coreg info")
            print(e)

        
        print("Local alignment Stage 2 horizontal calculation successful.")


    except Exception as e:
        print("Local alignment Stage 2 horizontal calculation failed.")
        raise e
    

# Apply Stage 2 local shifts to RGB, MS
for src, dst in [(local1_rgb, local2_rgb), (local1_ms, local2_ms), (local1_dsm, local2_dsm)]:
    if os.path.exists(dst):
        print(f"File {dst} already shifted. Skipping...")
    else:
        # Free memory 
        
        gc.collect()

        print("Shifting file: ", os.path.basename(src))
        apply_arosics_gcps(src, dst, local2_info) #consumes less memory
        print(f"Shift applied to {os.path.basename(src)}")


################### 3. DSM Vertical LOCAL ALIGNMENT ###################


vertical_local_dir = os.path.join(local2_dir, "DSM", "Vertical_local")
os.makedirs(vertical_local_dir, exist_ok=True)
local_vertical_path = os.path.join(vertical_local_dir, target_mission + "_aligned_local2_DSM.tif")
if os.path.exists(local_vertical_path):
    print("Vertical local alignment already processed. Skipping...")
else:
    # Read DSM and resample
    with rasterio.open(local2_dsm) as src:
        tgt_dsm_data = src.read()
        tgt_dsm_meta = src.meta.copy()
        print(tgt_dsm_meta)
        print(tgt_dsm_data)

        tgt_dsm_meta.update({"dtype": "float32"})
        tgt_dsm_data[np.isnan(tgt_dsm_data)] = 0

        src_nodata = 0

        # Initialize resampled target array matching reference dimensions
        resampled_tgt = np.full(
            (1, dem_meta_photo_resampled['height'], dem_meta_photo_resampled['width']),
            src_nodata,
            dtype=np.float32
        )

        try:
            # Reproject to reference grid before vertical shift calculation
            for band in range(tgt_dsm_meta['count']):
                reproject(
                    tgt_dsm_data[band], resampled_tgt[band],
                    src_transform=tgt_dsm_meta['transform'],
                    src_crs=tgt_dsm_meta['crs'],
                    dst_transform=dem_meta_photo_resampled['transform'],
                    dst_crs=dem_meta_photo_resampled['crs'],
                    resampling=Resampling.nearest,
                    src_nodata=src_nodata,
                    dst_nodata=src_nodata
                )
            
            # Update target metadata to match reference dimensions
            tgt_dsm_meta.update({
                'height': dem_meta_photo_resampled['height'],
                'width': dem_meta_photo_resampled['width'],
                'transform': dem_meta_photo_resampled['transform'],
                'crs': dem_meta_photo_resampled['crs']
            })

            dsm_band = resampled_tgt[DSM_BAND]
            # Exclude both 0 and the target nodata value
            valid_tgt_mask = (
                (resampled_tgt[0] != src_nodata) &
                (resampled_tgt[0] != 0)
            )

            tgt = np.median(dsm_band[valid_tgt_mask])
            print("the median of the date (excluding nodata) is: ", tgt)

            vertical_offset = ref - tgt

            print(f"Calculated Vertical Offset Correction: {vertical_offset} meters")
            resampled_tgt[DSM_BAND] = np.where(
                valid_tgt_mask, 
                resampled_tgt[DSM_BAND] + vertical_offset, 
                resampled_tgt[DSM_BAND]
            )
            
            # Write final vertically and locally aligned DSM
            with rasterio.open(local_vertical_path, 'w', **tgt_dsm_meta) as dst:
                dst.write(resampled_tgt)
            print("Vertical local alignment completed successfully.")
            
        except Exception as e:
            print("Vertical local alignment failed.")
            raise e