import matplotlib.pyplot as plt
import os
import rasterio
import numpy as np
from arosics import COREG, DeShifter
from raster_tools_ms import crop_raster_tile, split_bands, find_product_tiff, copy_if_missing, sanitize_image_metadata
import geopandas as gpd
from shapely.geometry import box
import pandas as pd
from rasterio.warp import reproject, Resampling
import pickle
import os
import gc
import geoarray.baseclasses as gab
import copyreg
from osgeo import gdal
import shutil


"""

Global alignment of missions from a reference. Based on the alignment pipeline:
https://github.com/VasquezVicente/ForestLandscapes/blob/main/LandscapeScripts/50ha_aligment_v2.py

"""


ALIGN_GLOBAL = True

# --- Patch geoarray's bool-dtype bug before any AROSICS calls ---
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


os.environ['JOBLIB_TEMP_FOLDER'] = 'D:\\uzcateguipaula\\joblib_tmp'
os.makedirs(os.environ['JOBLIB_TEMP_FOLDER'], exist_ok=True)

orignal_products_path = r"Products\Drone"


align_out_path = r"D:\uzcateguipaula\Aligned"#"paula_mavic_products\Aligned"#"D:\uzcateguipaula\Aligned"
cropped_path = os.path.join(align_out_path, "Product_cropped")


BCI_50ha_shapefile = os.path.join(align_out_path,"aux_files", "BCI_50ha_big_shape_all.gpkg")
BCI_50ha = gpd.read_file(BCI_50ha_shapefile)
BCI_50ha.to_crs(epsg=32617, inplace=True)
BCI_50ha = BCI_50ha.reset_index(drop=True)

missions_list = pd.read_excel(r"Raw\Drone\missions_processing.xlsx", sheet_name = "MAVIC_ALIGN_ALL")

missions_list['base'] = (
    missions_list['mission']
    .str.rsplit('_', n=1)
    .str[0]
)
missions_list['date'] = missions_list['mission'].str.extract(r'BCI_50ha_(\d{4}_\d{2}_\d{2})')[0]
missions_list['date'] = pd.to_datetime(missions_list['date'], format='%Y_%m_%d')

missions_list['antenna'] = np.where(
    (~missions_list['antenna'].isna()),

    missions_list['antenna'],
    'Unknown'
)

# order this: starting from "BCI_50ha_2024_11_12_M3E", forward. Then "BCI_50ha_2024_11_12_M3E" and the backwards. No need for 2 loops
reference_mission = "BCI_50ha_2024_11_12_M3E"
original_reference = reference_mission

# Sort chronologically
missions_list = missions_list.sort_values("date").reset_index(drop=True)


# Index of the reference mission
ref_idx = missions_list.index[
    missions_list["mission"] == reference_mission
][0]

first_mission = missions_list.iloc[0]["mission"]

# Forward: E F G (reference excluded)
missions_forward = missions_list.iloc[ref_idx + 1:].reset_index(drop=True)

# Backward: C B A (reference excluded)
missions_backward = missions_list.iloc[:ref_idx].iloc[::-1].reset_index(drop=True)


missions_processing_align = pd.concat(
    [
        missions_forward,
        missions_backward
    ],
    ignore_index=True,
)

# mission with PPK coordinate correction and very well aligned with other missions
reference_ortho = find_product_tiff(orignal_products_path, reference_mission, "Orthophoto")
#os.path.join(orignal_products_path, reference_mission, "Orthophoto", reference_mission + "_orthomosaic.tif") 
reference_dsm = find_product_tiff(orignal_products_path, reference_mission, "DSM")

#os.path.join(orignal_products_path, reference_mission, "DSM", reference_mission + "_dsm.tif")

## REFERENCE 
reference_path_cropped_ortho = os.path.join(cropped_path,"Orthomosaic", reference_mission + "_orthomosaic.tif")
reference_rgb_path = os.path.join( cropped_path, "RGB",reference_mission + "_RGB.tif")
reference_ms_path = os.path.join( cropped_path, "MS",reference_mission + "_MS.tif")
reference_path_cropped_dsm = os.path.join(cropped_path, "DSM", reference_mission + "_dsm.tif")

# Crop orthomosaic
os.makedirs(os.path.dirname(reference_path_cropped_ortho), exist_ok=True)

# crop again only if the rgb do not exists
if not os.path.exists(reference_rgb_path):
    crop_raster_tile(reference_ortho, reference_path_cropped_ortho, BCI_50ha)
    print("Done cropping reference orthomosaic")
else:
    print(f"Skipping {reference_path_cropped_ortho} because it already exists")

# Split orthomosaic
if os.path.exists(reference_rgb_path):
    print(f"Reference RGB already processed. Skipping...")
else:
    split_bands(reference_path_cropped_ortho,reference_rgb_path,[1,2,3,8])
    print("Reference RGB bands split done")

if os.path.exists(reference_ms_path):
    print(f"Reference MS bands for {reference_path_cropped_ortho} already processed. Skipping...")
else:
    split_bands(reference_path_cropped_ortho,reference_ms_path,[4,5,6,7,8])
    print("Reference MS bands split done")

# Crop DSM
os.makedirs(os.path.dirname(reference_path_cropped_dsm), exist_ok=True)
if not os.path.exists(reference_path_cropped_dsm):
    crop_raster_tile(reference_dsm, reference_path_cropped_dsm, BCI_50ha)
    print("Crop reference DSM done")
else:
    print(f"Skipping {reference_path_cropped_dsm} because it already exists")


# copy reference to the globally aligned folder. 
"""
copy_if_missing(
    reference_rgb_path,
    reference_rgb_path.replace("Product_cropped", "Product_global")
                      .replace("_RGB", "_aligned_global_RGB")
)

copy_if_missing(
    reference_ms_path,
    reference_ms_path.replace("Product_cropped", "Product_global")
                     .replace("_MS", "_aligned_global_MS")
)

copy_if_missing(
    reference_path_cropped_dsm,
    reference_path_cropped_dsm.replace("Product_cropped", "Product_global")
                              .replace("DSM/", "DSM/Vertical_global/")
                              .replace("_DSM", "_aligned_global_DSM")
)
"""
original_reference_rgb = reference_rgb_path
original_reference_dsm = reference_path_cropped_dsm

# just the cropping for now 

############# START OF LOOP ###################################################################################
for direction, missions_align in [("backwards", missions_backward), ("forward", missions_forward)]:

    missions_processing_align = missions_align
    reference_rgb_path = original_reference_rgb
    reference_path_cropped_dsm = original_reference_dsm

    print(f"Starting {direction} in time from reference {original_reference}")   

    for target_mission, target_mission_antenna in missions_processing_align[["mission", "antenna"]].itertuples(index=False):
        print(target_mission)
        try:
            #############  DATA PREPARATION  ###########################################################

            # mission TO ALIGN
            target_ortho = find_product_tiff(orignal_products_path, target_mission, "Orthophoto")
            #os.path.join(orignal_products_path, target_mission, "Orthophoto", target_mission+"_orthomosaic.tif")
            target_dsm = find_product_tiff(orignal_products_path, target_mission, "DSM")
            #os.path.join(orignal_products_path, target_mission, "DSM", target_mission+"_dsm.tif" )

            
            ### CROP TARGET PATH 
            target_path_cropped_ortho = os.path.join(cropped_path,"Orthomosaic", target_mission + "_orthomosaic.tif")
            target_rgb_path = os.path.join(cropped_path, "RGB", target_mission + "_RGB.tif")
            target_ms_path = os.path.join(cropped_path, "MS",target_mission + "_MS.tif")
            target_path_cropped_dsm = os.path.join(cropped_path, "DSM", target_mission + "_dsm.tif")


            os.makedirs(os.path.dirname(target_path_cropped_ortho), exist_ok=True)

            # crop only if rgb path does not exists
            if not os.path.exists(target_rgb_path):
                crop_raster_tile(target_ortho, target_path_cropped_ortho, BCI_50ha)
                print("Done cropping target orthomosaic")
            else:
                print(f"Skipping {target_path_cropped_ortho} because it already exists")


            #### SPLIT RGB AND MS BANDS
            if os.path.exists(target_rgb_path):
                print(f"Target RGB already processed. Skipping...")
            else:
                split_bands(target_path_cropped_ortho,target_rgb_path,[1,2,3,8])
                print("Target RGB bands split done")


            if os.path.exists(target_ms_path):
                print(f"Target MS bands for {target_path_cropped_ortho} already processed. Skipping...")
            else:
                split_bands(target_path_cropped_ortho,target_ms_path,[4,5,6,7,8])
                print("Target MS bands split done")


            #### CROP DSM 
            os.makedirs(os.path.dirname(target_path_cropped_dsm), exist_ok=True)
            if not os.path.exists(target_path_cropped_dsm):
                crop_raster_tile(target_dsm, target_path_cropped_dsm, BCI_50ha)
                print("Crop target DSM done")
            else:
                print(f"Skipping {target_path_cropped_dsm} because it already exists")


            #### FINISHED DATA PREPARATION 
            target_global_align_rgb = os.path.join(align_out_path, "Product_global", "RGB", target_mission + "_aligned_global_RGB.tif")
            target_global_align_ms = os.path.join(align_out_path, "Product_global", "MS", target_mission + "_aligned_global_MS.tif")
            target_global_align_dsm =  os.path.join(align_out_path, "Product_global", "DSM", target_mission + "_aligned_global_DSM.tif")

            ### Apply global alignment to all the bands #####
            products_to_align = [
                (target_rgb_path, target_global_align_rgb),
                (target_ms_path, target_global_align_ms),
                (target_path_cropped_dsm, target_global_align_dsm)
            ]

        except Exception as e:
            print(f"\nError processing {target_mission}: {e}")
            continue

        if ALIGN_GLOBAL:

            print(f"Using reference {reference_mission}")

            ############### GLOBAL ALIGNMENT ###############################################################################
            print("Start of global alignment")

            os.makedirs(os.path.join(align_out_path,'Product_global'), exist_ok=True)

            global_path = os.path.join(align_out_path, "Product_global", "Orthophoto", target_mission + "_aligned_global.tif")
            coreg_global_info = os.path.join(align_out_path, "Product_global", "COREG_RESULT", target_mission + "_coreg_info.pkl")

            if os.path.exists(coreg_global_info):
                print(f"Global alignment for {target_rgb_path} already processed. Skipping...")
                # load Coreg info
                with open(coreg_global_info, "rb") as f:
                    coreg_info = pickle.load(f)
            else:
                sanitize_image_metadata(reference_rgb_path)
                sanitize_image_metadata(target_rgb_path)

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
                    CR= COREG(reference_rgb_path, target_rgb_path, **kwargs2,ws=(2048,2048))
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
            os.makedirs(os.path.join(align_out_path, "Product_global", "DSM",'Vertical_global'), exist_ok=True)
            DSM_BAND = 0  # Assuming the DSM is the first band in the aligned global DSM file

            global_vertical_path = os.path.join(align_out_path, "Product_global", "DSM", 'Vertical_global', target_mission + "_aligned_global_DSM.tif")

            if os.path.exists(global_vertical_path):
                print("Vertical global alignment already processed. Skipping...")
            else:
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

                with rasterio.open(target_global_align_dsm) as src:
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

            print(f"Finished with mission {target_mission}")

            # if the mission does not have antenna keep the same reference...
            if target_mission_antenna == "Unknown":
                print("Keeping previous reference")
            else:
                # Set target as the reference of the next mission
                reference_mission = target_mission
                reference_rgb_path = target_global_align_rgb
                reference_path_cropped_dsm = target_global_align_dsm

