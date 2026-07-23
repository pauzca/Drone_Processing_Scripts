import os
import Metashape #fotogrametria
import numpy as np
import gc
import pandas as pd
import time
from datetime import datetime
import subprocess # need pdal and gdal to be installed for the cloud optimized format conversion

"""

Script to process multiple trinity flights over BCI
Only use for RGB flights

This is a modified version of the mavic_process script in https://github.com/VasquezVicente/ForestLandscapes/blob/main/LandscapeScripts/mavic_process.py. 

 - Include Antenna coordinate accuracy in the parameters of chunk.addPhotos. This way Metashape will fully use the coordinates from the antenna. 
 - When there is a bad allocation error (the computer ran out of memory) the process is retried.
 - Export pointcloud, dsm and orthomosaic in cloud optmized format

 
As long as the images are all in the Images directory the script should run fine

INPUT FILES NEEDED:

Raw/year/Mission_Name 
|
|- Images: contains JPG images the coordinates have already been corrected with the antenna.


OUTPUT FILES:
Products/year/Mission_Name
|
|- Project
    |- Mission_Name_medium.files: metashape project files 
    |- Mission_Name_medium: metashape project 
    |- Mission_Name_report.pdf: report of processing
|- Orthophoto
    |- Mission_Name.tif: orthomosaic
    |- Mission_Name.cog.tif: orthomosaic cloud optimized
|- Cloudpoint
    |- Mission_Name.las: pointcloud
    |- Mission_Name.copc.laz: pointcloud cloud optimized
|- DSM
    |- Mission_Name.tif: dsm
    |- Mission_Name.cog.tif: dsm cloud optimized


"""

# ── Retry wrapper ─────────────────────────────────────────────────────────────
def run_with_retry(fn, step_name="step", max_retries=5, wait_seconds=60):
    for attempt in range(1, max_retries + 1):
        try:
            print(f"  [{step_name}] Attempt {attempt}/{max_retries}...")
            fn()
            print(f"  [{step_name}] Success.")
            return True
        except MemoryError as e:
            if "bad allocation" in str(e).lower():
                print(f"  [{step_name}] Bad allocation on attempt {attempt}.")
                if attempt < max_retries:
                    print(f"  Waiting {wait_seconds}s before retry...")
                    time.sleep(wait_seconds)
                else:
                    print(f"  [{step_name}] Failed after {max_retries} attempts.")
                    return False
            else:
                raise
    return False



## START OF SCRIPT 

# For testing with just one mission and a few images only
TEST_MODE = False
TEST_N_IMAGES = 3

RAW_MISSIONS_DIRECTORY = r"Raw\Drone"
#trinity flight main folders
year= input("Enter the year of the flight: ")


missions= os.listdir(RAW_MISSIONS_DIRECTORY, year)
for i in range(len(missions)):
    print(f'{i+1}. {missions[i]}')

dir_input = input("Enter the mission identificatior (mission name) to be processed: ")
mission_names = dir_input.split(',')

# All the trinity missions should have geocorrected coordinates already.
antenna = input("Is antenna data available? (y/n) for each mission, comma separated: ")
antenna_available = antenna.split(',')

print(antenna_available)

missions_to_process = pd.DataFrame()

missions_to_process['mission_name'] = [m.strip() for m in mission_names]
missions_to_process['antenna'] = [m.strip() for m in antenna_available]


if TEST_MODE:
    missions_to_process = missions_to_process.head(1)

print(missions_to_process)

for idx, mission_row in missions_to_process.iterrows():
        mission = mission_row['mission_name']
        ppk_avaliable = missions_to_process['antenna'] == "y" # Set to 'True' if PPK data is available, otherwise 'False'

        mission_path = os.path.join(RAW_MISSIONS_DIRECTORY, year, mission)

        path = os.path.dirname(mission_path)

        dest = os.path.join(mission_path.replace('Raw','Products'),"Project",mission+"_medium.psx")

        try:
            print(f"Starting mission {mission}")
            doc = Metashape.Document()
            doc.save(dest)
            chunk = doc.addChunk()

            images_dir = os.path.join(mission_path, 'Images')


            photos = sorted([
                os.path.join(images_dir, f)
                for f in os.listdir(os.path.join(images_dir))
                if f.endswith(".JPG")
            ])

            if TEST_MODE:
                photos = photos[:TEST_N_IMAGES]


            chunk.addPhotos(photos, 
                                load_reference = True,
                                load_xmp_calibration = True,
                                load_xmp_orientation = True,
                                load_xmp_accuracy = True,
                                load_xmp_antenna = True
                                )


            doc.save(dest)

            print("\n=== ACCURACY VERIFICATION ===")

            accuracies = [cam.reference.accuracy for cam in chunk.cameras if cam.reference.accuracy]
            if accuracies:
                avg = np.mean(np.array(accuracies), axis=0)
                print(f"Cameras with accuracy: {len(accuracies)} / {len(chunk.cameras)}")
                print(f"Average: X={avg[0]:.4f}m, Y={avg[1]:.4f}m, Z={avg[2]:.4f}m")

            else:
                print("WARNING - No cameras with accuracy data found.")

                if ppk_avaliable:
                  # kill the process if no accuracy data is found, since it means that the PPK data was not loaded correctly
                    raise ValueError("No cameras with accuracy data found. Check antenna loading.")


            for cam in chunk.cameras:
                if cam.reference.location is not None and cam.reference.accuracy is None:   
                    print(f"WARNING: Camera {cam.label} has location but no accuracy. This may indicate an issue with PPK data loading.")



            out_crs = Metashape.CoordinateSystem("EPSG::32617")
            for camera in chunk.cameras:
                if camera.reference.location:
                    camera.reference.location = Metashape.CoordinateSystem.transform(camera.reference.location, chunk.crs, out_crs)

            chunk.crs = out_crs
            chunk.updateTransform()
            doc.save(dest)

            if not TEST_MODE:
                chunk.matchPhotos(downscale=0, keypoint_limit=40000, tiepoint_limit=4000, generic_preselection=True, reference_preselection=True)
                doc.save(dest)

                chunk.alignCameras(adaptive_fitting=True)
                doc.save(dest)

                # ── Retried steps ─────────────────────────────────────────────────
                depth_ok = run_with_retry(
                    lambda: chunk.buildDepthMaps(downscale=4, filter_mode=Metashape.AggressiveFiltering),
                    step_name="buildDepthMaps"
                )
                doc.save(dest)
                if not depth_ok:
                    raise RuntimeError("buildDepthMaps failed after all retries. Aborting mission.")

                has_transform = chunk.transform.scale and chunk.transform.rotation and chunk.transform.translation
                if not has_transform:
                    raise RuntimeError("Chunk has no transform. Alignment may have failed.")

                cloud_ok = run_with_retry(
                    lambda: chunk.buildPointCloud(),
                    step_name="buildPointCloud"
                )
                doc.save(dest)
                if not cloud_ok:
                    raise RuntimeError("buildPointCloud failed after all retries. Aborting mission.")
                # ─────────────────────────────────────────────────────────────────

                has_transform = chunk.transform.scale and chunk.transform.rotation and chunk.transform.translation
                if has_transform:
                    chunk.buildPointCloud()
                    doc.save(dest)
                    chunk.buildDem(source_data=Metashape.PointCloudData)
                    doc.save(dest)
                    chunk.buildOrthomosaic(surface_data=Metashape.ElevationData)
                    doc.save(dest)

                chunk.calibrateReflectance(use_sun_sensor=True)
                proj = Metashape.OrthoProjection()
                proj.crs = Metashape.CoordinateSystem("EPSG::32617")
                doc.save(dest)

                compression = Metashape.ImageCompression()
                compression.tiff_big = True

                chunk.exportReport(dest.replace('medium','report').replace('.psx','.pdf'))

                out_dir = mission_path.replace('Raw','Products')

                file_cloud = os.path.join(out_dir, "Cloudpoint", f"{mission}_cloud.las")
                os.makedirs(os.path.dirname(file_cloud), exist_ok=True)

                file_dsm = os.path.join(out_dir, 'DSM', mission+"_dsm.tif")
                os.makedirs(os.path.dirname(file_dsm), exist_ok=True)

                file_orthomosaic = os.path.join(out_dir, 'Orthophoto', mission+"_orthomosaic.tif")
                os.makedirs(os.path.dirname(file_orthomosaic), exist_ok=True)

                if chunk.point_cloud:
                    print("Saving pointcloud... ")
                    chunk.exportPointCloud(file_cloud, source_data=Metashape.PointCloudData, format=Metashape.PointCloudFormatLAS, crs=Metashape.CoordinateSystem("EPSG::32617"))
                    # SAVE THE PRODUCTS AS CLOUD OPTIMIZED FORMAT
                    print("Saving cloud optimized format")
                    cmd = [
                        "pdal",
                        "translate",
                        file_cloud,
                        file_cloud.replace(".tif", ".copc.laz"),
                        "--writer=writers.copc",
                        "--writers.copc.forward=all",
                    ]
                    print(f"Converting to COPC: {mission}")
                    try:
                        subprocess.run(cmd, check=True)
                    except FileNotFoundError:
                        print("PDAL was not found. Make sure PDAL is installed and available in PATH.")
                    except subprocess.CalledProcessError as error:
                        print(f"PDAL failed for {mission}: {error}")

                if chunk.elevation:
                    print("Saving DSM... ")
                    chunk.exportRaster(file_dsm, source_data=Metashape.ElevationData, projection=proj)
                    print("Saving cloud optimized format")
                    cmd = [
                        "gdal_translate",
                        "-of", "COG",
                        "-co", "COMPRESS=DEFLATE",
                        "-co", "PREDICTOR=2",
                        "-co", "LEVEL=9",
                        "-co", "BIGTIFF=IF_SAFER",
                        "-co", "OVERVIEWS=AUTO",
                        "-co", "BLOCKSIZE=512",
                        "-co", "NUM_THREADS=ALL_CPUS",
                        file_dsm,
                        file_dsm.replace(".tif", ".cog.tif"),
                    ]

                    print(f"Converting DSM to COG: {mission}")
                    try:
                        subprocess.run(cmd, check=True)
                    except subprocess.CalledProcessError as error:
                        print(f"GDAL failed for {mission}: {error}")

                if chunk.orthomosaic:
                    print("Saving Orthomosaic... ")
                    chunk.exportRaster(file_orthomosaic, source_data=Metashape.OrthomosaicData, projection=proj, image_compression=compression)
                    print("Saving cloud optimized format")
                    cmd = [
                        "gdal_translate",
                        "-of", "COG",
                        "-co", "COMPRESS=DEFLATE",
                        "-co", "PREDICTOR=2",
                        "-co", "LEVEL=9",
                        "-co", "BIGTIFF=IF_SAFER",
                        "-co", "OVERVIEWS=AUTO",
                        "-co", "BLOCKSIZE=512",
                        "-co", "NUM_THREADS=ALL_CPUS",
                        file_orthomosaic,
                        file_orthomosaic.replace(".tif", ".cog.tif"),
                    ]

                    print(f"Converting Orthomosaic to COG: {mission}")
                    try:
                        subprocess.run(cmd, check=True)
                    except subprocess.CalledProcessError as error:
                        print(f"GDAL failed for {mission}: {error}")


                print(f'Processing finished: {mission}')


        except Exception as e:
            print(f'Error processing: {mission} -- {e}')