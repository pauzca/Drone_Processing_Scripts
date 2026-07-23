import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor

"""

Converts all files in a folder to cloud optimized geotiff

"""

# RGB or MS or DSM
PRODUCT = "Orthophoto"

source_folder = os.path.join(r"\paula_mavic_products\Aligned\Product_global", PRODUCT)
output_folder = os.path.join(r"paula_mavic_products\Aligned\Product_global_COG", PRODUCT)

local_staging_folder = r"D:\uzcateguipaula\COG_staging"

os.makedirs(output_folder, exist_ok=True)
os.makedirs(local_staging_folder, exist_ok=True)


def copy_cog_to_server(local_cog, server_cog):
    """Copy through a temporary filename, then rename when complete."""
    partial_file = server_cog + ".partial"

    try:
        if os.path.exists(partial_file):
            os.remove(partial_file)

        print(f"Uploading: {os.path.basename(server_cog)}")
        shutil.copy2(local_cog, partial_file)
        os.replace(partial_file, server_cog)

        print(f"Upload complete: {os.path.basename(server_cog)}")

        # Remove the local COG only after a successful upload.
        os.remove(local_cog)

    except OSError as error:
        print(f"Upload failed for {local_cog}: {error}")


missions_list = [
    filename
    for filename in os.listdir(source_folder)
    if filename.lower().endswith((".tif", ".tiff"))
]

upload_futures = []

# One upload thread is usually best when reading the next source
# from the same network server.
with ThreadPoolExecutor(max_workers=1) as upload_executor:

    for mission in missions_list:
        server_input = os.path.join(source_folder, mission)

        base_name, _ = os.path.splitext(mission)
        output_filename = f"{base_name}.cog.tif"

        server_output = os.path.join(output_folder, output_filename)
        local_input = os.path.join(local_staging_folder, mission)
        local_output = os.path.join(local_staging_folder, output_filename)

        if os.path.exists(server_output):
            print(f"Already completed: {output_filename}")
            continue

        # Copy the source to the local SSD.
        if not os.path.exists(local_input):
            print(f"Downloading source: {mission}")

            try:
                shutil.copy2(server_input, local_input)
            except OSError as error:
                print(f"Download failed for {mission}: {error}")
                continue

        # Create the COG locally.
        if not os.path.exists(local_output):
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
                local_input,
                local_output,
            ]

            print(f"Converting locally: {mission}")

            try:
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError as error:
                print(f"GDAL failed for {mission}: {error}")
                continue

        # The original staged TIFF is no longer needed.
        try:
            os.remove(local_input)
        except OSError as error:
            print(f"Could not remove local source {local_input}: {error}")

        # Upload in the background while the loop handles the next file.
        future = upload_executor.submit(
            copy_cog_to_server,
            local_output,
            server_output,
        )
        upload_futures.append(future)

    print("All conversions submitted. Waiting for remaining uploads...")

    for future in upload_futures:
        try:
            future.result()
        except Exception as error:
            print(f"Unexpected upload error: {error}")

print("Processing finished.")