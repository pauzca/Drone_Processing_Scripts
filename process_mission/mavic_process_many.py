import os
import Metashape
import numpy as np
import gc
import time
import logging
import sys
from datetime import datetime

"""

For Multispectral Mavic Missions

This is a modified version of the mavic_process script in https://github.com/VasquezVicente/ForestLandscapes/blob/main/LandscapeScripts/mavic_process.py. 

 - Include Antenna coordinate accuracy in the parameters of chunk.addPhotos. This way Metashape will fully use the coordinates from the antenna. 
 - When there is a bad allocation error (the computer ran out of memory) the process is retried.

"""


TEST_MODE = False



# ── Config ────────────────────────────────────────────────────────────────────
missions_path = r"D:\uzcateguipaula\Raw"

# List of all the missions to be processed.  This is the name of the mission folder. 
# And will be the same name of the products folder for that mission
missions_dir = [
    "BCI_50ha_2025_12_02_M3E",
]

# List of the antenna used in that mission.
# For multispectral flights the antenna info must be copied to the other bands. So its important to make the distinction
antenna_list = [
    'RTK'
]

#time.sleep(7200)

# ── Logging setup ─────────────────────────────────────────────────────────────
def setup_logger(log_dir):
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"processing_{timestamp}.log")

    # Get the root logger and reset it — basicConfig won't work after first call
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Remove any existing handlers from previous missions
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)

    # Add fresh file handler for this mission
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(handler)
    return log_path

def log(msg, level="info"):
    """Print to console and write to log file simultaneously."""
    print(msg)
    getattr(logging, level)(msg)

""""
Since the computer sometimes runs out of memory and stops the processing, 
during the depth map construction or pointcloud construction
This function is to retry and avoid killing the process.
"""
# ── Retry wrapper ─────────────────────────────────────────────────────────────
def run_with_retry(fn, step_name="step", max_retries=5, wait_seconds=60):
    for attempt in range(1, max_retries + 1):
        try:
            log(f"  [{step_name}] Attempt {attempt}/{max_retries}...")
            fn()
            log(f"  [{step_name}] Success.")
            return True
        except MemoryError as e:
            if "bad allocation" in str(e).lower():
                log(f"  [{step_name}] Bad allocation on attempt {attempt}.", level="warning")
                if attempt < max_retries:
                    log(f"  Waiting {wait_seconds}s before retry...")
                    time.sleep(wait_seconds)
                else:
                    log(f"  [{step_name}] Failed after {max_retries} attempts.", level="error")
                    return False
            else:
                raise
    return False


# ── Helpers ───────────────────────────────────────────────────────────────────
# Combines the multispectral and RGB images
def create_combined(photos_rgb):
    combined = []
    for i in range(len(photos_rgb)):
        combined.extend([
            photos_rgb[i],
            photos_rgb[i].replace("RGB", "Multispectral").replace("_D.JPG", "_MS_G.TIF"),
            photos_rgb[i].replace("RGB", "Multispectral").replace("_D.JPG", "_MS_R.TIF"),
            photos_rgb[i].replace("RGB", "Multispectral").replace("_D.JPG", "_MS_NIR.TIF"),
            photos_rgb[i].replace("RGB", "Multispectral").replace("_D.JPG", "_MS_RE.TIF")
        ])
    return combined



# Iterates over every mission processig it. 
# Log files will be created for every mission in the directory where this script is located
# ── Main loop ─────────────────────────────────────────────────────────────────
for i, mission in enumerate(missions_dir):
    log_dir = os.path.join(".\Process", mission, "Logs")
    log_path = setup_logger(log_dir)
    log(f"Log file: {log_path}")
    log(f"TEST_MODE: {TEST_MODE}")

    try:
        log(f"\n{'='*60}")
        log(f"Starting mission: {mission}")
        log(f"{'='*60}")

        images_dir = os.path.join(missions_path, mission)
        antenna = antenna_list[i]

        path = os.path.dirname(images_dir)
        folders = [folder for folder in os.listdir(images_dir)
                   if folder.startswith('DJI') and os.path.isdir(os.path.join(images_dir, folder))]

        dest = os.path.join(images_dir.replace('Raw', 'Products'), "Project", mission + "_medium.psx")
        dest2 = os.path.join(images_dir.replace('Raw', 'Products'), "Project")
        
        os.makedirs(dest2, exist_ok=True)

        doc = Metashape.Document()
        doc.save(dest)
        chunk = doc.addChunk()
        all_combined = []

        for flights in folders:
            log(f'Loading photos: {flights}')
            try:
                photos_rgb_nth = sorted([
                    os.path.join(images_dir, flights, 'RGB', f)
                    for f in os.listdir(os.path.join(images_dir, flights, 'RGB'))
                    if f.endswith(".JPG")
                ])
                photos_rgb_nth = create_combined(photos_rgb_nth)
                all_combined.extend(photos_rgb_nth)
            except Exception as e:
                log(f'WARNING: Failed to load photos from flight {flights}: {e} — skipping', level="warning")
                continue

        if antenna == 'None':
            chunk.addPhotos(all_combined,
                            filegroups=[5] * (int(len(all_combined) / 5)),
                            layout=Metashape.MultiplaneLayout)
        else:
            chunk.addPhotos(all_combined,
                            filegroups=[5] * (int(len(all_combined) / 5)),
                            layout=Metashape.MultiplaneLayout,
                            load_reference=True,
                            load_xmp_calibration=True,
                            load_xmp_orientation=True,
                            load_xmp_accuracy=True,
                            load_xmp_antenna=True)

        if antenna == 'PPK':
            try:
                log("Copying PPK from georeference images")
                images_ppk = []
                for flights in folders:
                    log(f'Processing PPK: {flights}')
                    try:
                        photos_dir = os.path.join(images_dir, flights, "Georeference", 'tagged_RGB')
                        photos_rgb_nth = sorted([f for f in os.listdir(photos_dir) if f.endswith(".JPG")])
                        images_ppk.extend([os.path.join(photos_dir, photo) for photo in photos_rgb_nth])
                    except Exception as e:
                        log(f'WARNING: Failed to load PPK photos from flight {flights}: {e} — skipping', level="warning")
                        continue

                doc2 = Metashape.Document()
                chunk_ppk = doc2.addChunk()
                chunk_ppk.addPhotos(images_ppk,
                                    load_reference=True,
                                    load_xmp_calibration=True,
                                    load_xmp_orientation=True,
                                    load_xmp_accuracy=True,
                                    load_xmp_antenna=True)

                log("\n=== PPK ACCURACY VERIFICATION ===")
                accuracies = [cam.reference.accuracy for cam in chunk_ppk.cameras if cam.reference.accuracy]
                if accuracies:
                    avg = np.mean(np.array(accuracies), axis=0)
                    log(f"Cameras with accuracy: {len(accuracies)} / {len(chunk_ppk.cameras)}")
                    log(f"Average: X={avg[0]:.4f}m, Y={avg[1]:.4f}m, Z={avg[2]:.4f}m")
                else:
                    raise ValueError("No cameras with accuracy data found. Check emlid process.")
                    

                ppk_data = {cam.label: {'location': cam.reference.location,
                                        'accuracy': cam.reference.accuracy}
                            for cam in chunk_ppk.cameras}

                for camera in chunk.cameras:
                    if camera.label in ppk_data:
                        camera.reference.location = ppk_data[camera.label]['location']
                        camera.reference.accuracy = ppk_data[camera.label]['accuracy']
                    elif '_MS_' in camera.label:
                        rgb_label = camera.label.split('_MS_')[0] + '_D'
                        if rgb_label in ppk_data:
                            camera.reference.location = ppk_data[rgb_label]['location']
                            camera.reference.accuracy = ppk_data[rgb_label]['accuracy']
                    else:
                        log(f"WARNING: No PPK data for {camera.label}, setting 10m accuracy", level="warning")
                        camera.reference.accuracy = Metashape.Vector([10, 10, 10])

            except Exception as e:
                log(f'ERROR in PPK processing for mission {mission}: {e}', level="error")
                log('Moving to next mission...')

        doc.save(dest)

        if antenna != 'None':
            log("\n=== FINAL ACCURACY VERIFICATION ===")
            accuracies = [cam.reference.accuracy for cam in chunk.cameras if cam.reference.accuracy]
            if accuracies:
                avg = np.mean(np.array(accuracies), axis=0)
                log(f"Cameras with accuracy: {len(accuracies)} / {len(chunk.cameras)}")
                log(f"Average: X={avg[0]:.4f}m, Y={avg[1]:.4f}m, Z={avg[2]:.4f}m")
            else:
                raise ValueError("No cameras with accuracy data found. Check antenna loading.")

            for cam in chunk.cameras:
                if cam.reference.location is not None and cam.reference.accuracy is None:
                    log(f"WARNING: Camera {cam.label} has location but no accuracy.", level="warning")
        else:
            log("\n=== USING 10m ACCURACY ===")

        if not TEST_MODE:
            out_crs = Metashape.CoordinateSystem("EPSG::32617")
            for camera in chunk.cameras:
                if camera.reference.location:
                    camera.reference.location = Metashape.CoordinateSystem.transform(
                        camera.reference.location, chunk.crs, out_crs)
            chunk.crs = out_crs
            chunk.updateTransform()
            doc.save(dest)

            log("Matching photos...")
            chunk.matchPhotos(downscale=0, keypoint_limit=40000, tiepoint_limit=4000,
                              generic_preselection=True, reference_preselection=True)
            doc.save(dest)

            log("Aligning cameras...")
            chunk.alignCameras(adaptive_fitting=True)
            doc.save(dest)
            log("Alignment complete.")

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

            chunk.exportReport(dest.replace('medium', 'report').replace('.psx', '.pdf'))

            out_dir = images_dir.replace('Raw', 'Products')
            folder_cloud = os.path.join(out_dir, 'Cloudpoint')
            os.makedirs(folder_cloud, exist_ok=True)
            folder_dsm = os.path.join(out_dir, 'DSM')
            os.makedirs(folder_dsm, exist_ok=True)
            folder_orthomosaic = os.path.join(out_dir, 'Orthophoto')
            os.makedirs(folder_orthomosaic, exist_ok=True)

            if chunk.point_cloud:
                chunk.exportPointCloud(
                    os.path.join(folder_cloud, mission + "_cloud.las"),
                    source_data=Metashape.PointCloudData,
                    format=Metashape.PointCloudFormatLAS,
                    crs=Metashape.CoordinateSystem("EPSG::32617"))
            if chunk.elevation:
                chunk.exportRaster(
                    os.path.join(folder_dsm, mission + "_dsm.tif"),
                    source_data=Metashape.ElevationData, projection=proj)
            if chunk.orthomosaic:
                chunk.exportRaster(
                    os.path.join(folder_orthomosaic, mission + "_orthomosaic.tif"),
                    source_data=Metashape.OrthomosaicData,
                    projection=proj, image_compression=compression)

            log(f'Processing finished: {mission}')

    except Exception as e:
        log(f"Error: {e}. With mission {mission}, moving on to next mission", level="error")
