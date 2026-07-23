import os
import Metashape
import numpy as np
import gc
import time
import logging
import sys
from datetime import datetime


TEST_MODE = False

"""
This script didint work. Computer ran out of memory. Might work with more RAM for bigger missions..

Processing all the images at once can make the computer run out of memory 
To avoid this we can divide the project in different chunks, process a smaller more maneagable amount of images an dthen merge them back together

To do this:

1. Create one chunk with all the images and align cameras for all of them
2. Divide the chunk into 4 chunks with 50% overlap
3. Process each chunk independently, that is: build depth map and pointcloud
4. Merge the chunks back together using the function merge chunk (we will have a merged pointcloud)
5. Build dsm and orthomosaic of the merged chunk. 

"""

NCOLS = 2
NROWS = 1


# ── Config ────────────────────────────────────────────────────────────────────
missions_path = r"D:\uzcateguipaula\Raw"

missions_dir = [
    "BCI_50ha_2024_08_12_M3E"
]

antenna_list = [
    'PPK'
]



# ── Logging setup ─────────────────────────────────────────────────────────────
def setup_logger(log_dir):
    """Set up logger that writes to a timestamped log file."""
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"processing_{timestamp}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
        ]
    )
    return log_path

def log(msg, level="info"):
    """Print to console and write to log file simultaneously."""
    print(msg)
    getattr(logging, level)(msg)


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


# ── Chunk splitting (region-based, following Agisoft's official pattern) ──────
def is_identity_matrix(matrix):
    for i in range(matrix.size[0]):
        for j in range(matrix.size[1]):
            if i == j:
                if matrix[i, j] != 1.0:
                    return False
            elif matrix[i, j]:
                return False
    return True
 

# ── Chunking helpers ──────────────────────────────────────────────────────────
def split_chunk_into_grid(doc, source_chunk, parts_x=2, parts_y=2, overlap_pct=40):
    """
    Split source_chunk into a grid of (parts_x * parts_y) sub-chunks by
    bounding-region, following Agisoft's official split_in_chunks_dialog.py pattern.
 
    Each sub-chunk is a full copy (cameras included) with its region narrowed
    to one grid cell, expanded by overlap_pct percent. Metashape internally
    restricts processing (depth maps / point cloud) to cameras relevant to
    that region.
 
    overlap_pct: percentage to expand each cell's region, e.g. 40 = +40%
    """
    # Normalize the transform the way Agisoft's script does, to avoid
    # degenerate region math when the chunk transform isn't already "clean"
    t = source_chunk.transform.matrix
    if (not source_chunk.transform.translation
            or not source_chunk.transform.translation.norm()
            or source_chunk.transform.scale == 1
            or is_identity_matrix(source_chunk.transform.rotation)):
        source_chunk.transform.matrix = t
 
    original_region = source_chunk.region
    r_center = original_region.center
    r_rotate = original_region.rot
    r_size = original_region.size
 
    x_scale = r_size.x / parts_x
    y_scale = r_size.y / parts_y
    z_scale = r_size.z
 
    offset = r_center - r_rotate * r_size / 2.0
 
    created_chunks = []
 
    for j in range(1, parts_y + 1):
        for i in range(1, parts_x + 1):
            new_chunk = source_chunk.copy(items=[])  # full copy, cameras included
            new_chunk.label = f"tile_{i}_{j}"
            if new_chunk.model:
                new_chunk.model.clear()
 
            new_region = Metashape.Region()
            new_rot = r_rotate
            new_center = Metashape.Vector([(i - 0.5) * x_scale, (j - 0.5) * y_scale, 0.5 * z_scale])
            new_center = offset + new_rot * new_center
 
            new_size = Metashape.Vector([x_scale, y_scale, z_scale])
            new_region.size = new_size * (1 + overlap_pct / 100)
            new_region.center = new_center
            new_region.rot = new_rot
 
            new_chunk.region = new_region
            created_chunks.append(new_chunk)
            log(f"  Created {new_chunk.label}")
 
    return created_chunks, original_region
 


def merge_tile_chunks(doc, tile_chunks_index, tile_chunks_reference):
    """Merge point clouds from all tiles back into one chunk."""
    log("\n--- Merging tile chunks ---")
    doc.alignChunks(
        chunks = tile_chunks,
        reference = [tile_chunks_reference],
        method = 2,
        downscale = 0 # alignment accuracy set to highest
    )
    doc.save()

    chunk_merged = doc.mergeChunks(
        chunks= tile_chunks,
        copy_depth_maps=True,
        copy_point_clouds=True,
        merge_assets=True,
        merge_markers=True
    )
    doc.save()

    print("merge chunk worked")
    return chunk_merged


# ── Other helpers ─────────────────────────────────────────────────────────────
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



# ── Main loop ─────────────────────────────────────────────────────────────────
for i, mission in enumerate(missions_dir):
    log_dir = os.path.join(missions_path.replace('Raw', 'Products'), mission, "Logs")
    log_path = setup_logger(log_dir)
    log(f"Log file: {log_path}")
    log(f"TEST_MODE: {TEST_MODE}")
    try:
        log(f"\n{'='*60}")
        log(f"Starting mission: {mission}")
        log(f"{'='*60}")

        images_dir = os.path.join(missions_path, mission)
        antenna = antenna_list[i]

        folders = [folder for folder in os.listdir(images_dir)
                   if folder.startswith('DJI') and os.path.isdir(os.path.join(images_dir, folder))]

        dest = os.path.join(images_dir.replace('Raw', 'Products'), "Project", mission + "_medium.psx")
        dest2 = os.path.join(images_dir.replace('Raw', 'Products'), "Project")
        os.makedirs(dest2, exist_ok=True)

        doc = Metashape.Document()
        doc.save(dest)
        chunk = doc.addChunk()
        chunk.label = "full_alignment"
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
                        images_ppk.extend([os.path.join(photos_dir, p) for p in photos_rgb_nth])
                    except Exception as e:
                        log(f'WARNING: Failed to load PPK photos from {flights}: {e} — skipping', level="warning")
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
                    raise ValueError("No PPK accuracy data found. Check emlid process.")

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
            log("Alignment complete on full chunk.")

            # ── Split into tiles ──────────────────────────────────────────────
            log("\nSplitting into 2x1 tiles...")
            tile_chunks = split_chunk_into_grid(doc, chunk, n_cols=NCOLS, n_rows=NROWS, overlap=0.4)
            doc.save(dest)
            log(f"Created {len(tile_chunks)} tiles.")

            # ── Build depth maps + point cloud per tile ───────────────────────
            successful_tiles = []
            for tile in tile_chunks:
                log(f"\n--- Processing tile: {tile.label} ---")
                doc.save(dest)

                depth_ok = run_with_retry(
                    lambda t=tile: t.buildDepthMaps(
                        downscale=4, filter_mode=Metashape.AggressiveFiltering),
                    step_name=f"{tile.label}/buildDepthMaps"
                )
                if not depth_ok:
                    raise RuntimeError(f"{tile.label} buildDepthMaps failed after all retries. Aborting mission.")

                cloud_ok = run_with_retry(
                    lambda t=tile: t.buildPointCloud(),
                    step_name=f"{tile.label}/buildPointCloud"
                )
                if not cloud_ok:
                    raise RuntimeError(f"{tile.label} buildPointCloud failed after all retries. Aborting mission.")

                successful_tiles.append(tile)
                doc.save(dest)
                log(f"  Tile {tile.label} complete.")

            # ── Merge tiles ───────────────────────────────────────────────────
            successful_tiles_index = np.arange(1, NCOLS*NROWS + 1)
            tile_chunks_reference = successful_tiles_index[0]
            merged_chunk = merge_tile_chunks(doc, successful_tiles_index, tile_chunks_reference)
            doc.save(dest)

            # ── DEM + ortho on merged chunk ───────────────────────────────────
            has_transform = (merged_chunk.transform.scale and
                             merged_chunk.transform.rotation and
                             merged_chunk.transform.translation)

            if not has_transform:
                raise RuntimeError("Merged chunk has no transform. Cannot build DEM/ortho.")

            log("Building DEM...")
            merged_chunk.buildDem(source_data=Metashape.PointCloudData)
            doc.save(dest)

            log("Building orthomosaic...")
            merged_chunk.buildOrthomosaic(surface_data=Metashape.ElevationData)
            doc.save(dest)

            merged_chunk.calibrateReflectance(use_sun_sensor=True)
            proj = Metashape.OrthoProjection()
            proj.crs = Metashape.CoordinateSystem("EPSG::32617")
            doc.save(dest)

            compression = Metashape.ImageCompression()
            compression.tiff_big = True

            merged_chunk.exportReport(dest.replace('medium', 'report').replace('.psx', '.pdf'))

            out_dir = images_dir.replace('Raw', 'Products')
            folder_cloud = os.path.join(out_dir, 'Cloudpoint')
            os.makedirs(folder_cloud, exist_ok=True)
            folder_dsm = os.path.join(out_dir, 'DSM')
            os.makedirs(folder_dsm, exist_ok=True)
            folder_orthomosaic = os.path.join(out_dir, 'Orthophoto')
            os.makedirs(folder_orthomosaic, exist_ok=True)

            if merged_chunk.point_cloud:
                log("Exporting point cloud...")
                merged_chunk.exportPointCloud(
                    os.path.join(folder_cloud, mission + "_cloud.las"),
                    source_data=Metashape.PointCloudData,
                    format=Metashape.PointCloudFormatLAS,
                    crs=Metashape.CoordinateSystem("EPSG::32617"))
            if merged_chunk.elevation:
                log("Exporting DSM...")
                merged_chunk.exportRaster(
                    os.path.join(folder_dsm, mission + "_dsm.tif"),
                    source_data=Metashape.ElevationData, projection=proj)
            if merged_chunk.orthomosaic:
                log("Exporting orthomosaic...")
                merged_chunk.exportRaster(
                    os.path.join(folder_orthomosaic, mission + "_orthomosaic.tif"),
                    source_data=Metashape.OrthomosaicData,
                    projection=proj, image_compression=compression)

            log(f'Processing finished: {mission}')

    except Exception as e:
        log(f"Error: {e}. With mission {mission}, moving on to next mission", level="error")

log("\nAll missions attempted")