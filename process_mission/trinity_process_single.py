import os
import Metashape #fotogrametria
import numpy as np
import gc
import subprocess # need pdal and gdal to be installed for the cloud optimized format conversion

"""

Process only one RGB trinity mission

"""


TEST_MODE = True
TEST_N_IMAGES = 3


print(TEST_MODE)


mission = "BCI_50ha_2026_06_10"

# Configuration
mission_path = os.path.join(r"Raw\Drone\2026", mission + "_Trinity")
ppk_avaliable = 'True'  # Set to 'True' if PPK data is available, otherwise 'False'

path = os.path.dirname(mission_path)

dest = os.path.join(mission_path.replace('Raw','Products'),"Project",mission+"_medium.psx")


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

print(photos)

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
    print("No cameras with accuracy data found.")
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

    chunk.buildDepthMaps(downscale=4, filter_mode=Metashape.AggressiveFiltering)
    doc.save(dest)

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
