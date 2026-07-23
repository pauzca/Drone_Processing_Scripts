import os
import Metashape #fotogrametria
import time
import subprocess # need pdal and gdal to be installed for the cloud optimized format conversion

"""
If mission processing fails at any point this script can be used to take over where it was left.
"""

# ── Retry wrapper ─────────────────────────────────────────────────────────────
def run_with_retry(fn, step_name="step", max_retries=5, wait_seconds=60):
    for attempt in range(1, max_retries + 1):
        try:
            fn()
            return True
        except MemoryError as e:
            if "bad allocation" in str(e).lower():
                if attempt < max_retries:
                    time.sleep(wait_seconds)
                else:
                    return False
            else:
                raise
    return False


images_dir =   r"D:\uzcateguipaula\Raw"

# Name of the mission
mission = "BCI_50ha_2025_08_04_M3E"
project_dir = os.path.join(r"D:\uzcateguipaula\Products\BCI_50ha_2025_08_04_M3E\Project", mission + "_medium.psx")


dest = project_dir
doc = Metashape.Document()
doc.open(project_dir, read_only=False)   
chunk = doc.chunks[0]  # Assuming the first chunk is the one we want to process
print(chunk.label)


# Comment out the parts it has done already

#chunk.matchPhotos(downscale=0, keypoint_limit=40000, tiepoint_limit=4000, generic_preselection=True, reference_preselection=True)
#doc.save(dest)

#chunk.alignCameras(adaptive_fitting=True)
#doc.save(dest)

#chunk.buildDepthMaps(downscale=4, filter_mode=Metashape.AggressiveFiltering)
#doc.save(dest)
has_transform = chunk.transform.scale and chunk.transform.rotation and chunk.transform.translation
if has_transform:
    cloud_ok = run_with_retry(lambda: chunk.buildPointCloud(),step_name="buildPointCloud")
    doc.save(dest)
    if not cloud_ok:
        raise RuntimeError("buildPointCloud failed after all retries. Aborting mission.")
    chunk.buildDem(source_data=Metashape.PointCloudData)
    doc.save(dest)
    chunk.buildOrthomosaic(surface_data=Metashape.ElevationData)
    doc.save(dest)

chunk.calibrateReflectance(use_sun_sensor=True)
proj = Metashape.OrthoProjection()
proj.crs = Metashape.CoordinateSystem("EPSG::32617")
doc.save()

compression = Metashape.ImageCompression()
compression.tiff_big = True

chunk.exportReport(dest.replace('medium','report').replace('.psx','.pdf'))

out_dir = os.path.join(images_dir.replace('Raw','Products'), mission)
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
