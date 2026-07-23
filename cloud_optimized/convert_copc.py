import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

"""

Converts all the mission's pointclouds to cloud optimized format

"""

def find_product_pointcloud(missions_main_path, mission_name, product_name="Cloudpoint"):
    """Return the Cloudpoint folder and the most recently modified LAS file."""
    mission_name = str(mission_name).strip()
    mission_parts = mission_name.split("_")

    if len(mission_parts) < 3:
        print(f"Could not determine year from mission name: {mission_name}")
        return None

    mission_year = mission_parts[2]
    mission_folder = os.path.join(missions_main_path, mission_year, mission_name)
    product_path = os.path.join(mission_folder, product_name)

    if not os.path.isdir(mission_folder):
        print(f"Mission folder not found: {mission_folder}")
        return None

    if not os.path.isdir(product_path):
        print(f"Cloudpoint folder not found: {product_path}")
        return None

    try:
        product_files = [filename for filename in os.listdir(product_path) if filename.lower().endswith(".las") and os.path.isfile(os.path.join(product_path, filename))]
    except OSError as error:
        print(f"Could not read folder {product_path}: {error}")
        return None

    if not product_files:
        print(f"No LAS files found in: {product_path}")
        return None

    product_files.sort(key=lambda filename: os.path.getmtime(os.path.join(product_path, filename)), reverse=True)
    most_recent_file = os.path.join(product_path, product_files[0])

    print(f"Selected LAS: {os.path.basename(most_recent_file)}")
    return product_path, most_recent_file


def copy_copc_to_server(local_copc, server_copc):
    """Copy through a temporary filename and rename when complete."""
    partial_file = server_copc + ".partial"
    filename = os.path.basename(server_copc)

    try:
        if os.path.exists(partial_file):
            os.remove(partial_file)

        print(f"Uploading: {filename}")
        shutil.copy2(local_copc, partial_file)

        if os.path.getsize(local_copc) != os.path.getsize(partial_file):
            raise OSError("Uploaded file size does not match the local COPC file.")

        os.replace(partial_file, server_copc)
        print(f"Upload complete: {filename}")

        os.remove(local_copc)
        return True

    except OSError as error:
        print(f"Upload failed for {filename}: {error}")
        return False


missions_main_path = r"Products\Drone"
missions_excel = r"Raw\Drone\missions_processing.xlsx"
local_staging_folder = r"D:\uzcateguipaula\COPC_staging"

os.makedirs(local_staging_folder, exist_ok=True)

missions_df = pd.read_excel(missions_excel, sheet_name="MAVIC_PUBLICATION")
missions_list = missions_df["mission"].dropna().astype(str).str.strip().drop_duplicates().tolist()

print(f"Found {len(missions_list)} missions.")

upload_futures = {}

with ThreadPoolExecutor(max_workers=1) as upload_executor:

    for index, mission in enumerate(missions_list, start=1):
        print()
        print("=" * 70)
        print(f"Processing {index}/{len(missions_list)}: {mission}")
        print("=" * 70)

        found = find_product_pointcloud(missions_main_path, mission)

        if found is None:
            continue

        server_folder, server_input = found

        output_filename = f"{mission}.copc.laz"
        server_output = os.path.join(server_folder, output_filename)
        local_input = os.path.join(local_staging_folder, os.path.basename(server_input))
        local_output = os.path.join(local_staging_folder, output_filename)

        if os.path.isfile(server_output):
            print(f"Already completed: {server_output}")
            continue

        if not os.path.isfile(local_input):
            print(f"Downloading source: {server_input}")

            try:
                shutil.copy2(server_input, local_input)
            except OSError as error:
                print(f"Download failed for {mission}: {error}")
                continue
        else:
            print(f"Local LAS already exists: {local_input}")

        if not os.path.isfile(local_output):
            cmd = [
                "pdal",
                "translate",
                local_input,
                local_output,
                "--writer=writers.copc",
                "--writers.copc.forward=all",
            ]

            print(f"Converting to COPC: {mission}")

            try:
                subprocess.run(cmd, check=True)
            except FileNotFoundError:
                print("PDAL was not found. Make sure PDAL is installed and available in PATH.")
                break
            except subprocess.CalledProcessError as error:
                print(f"PDAL failed for {mission}: {error}")
                continue

            print(f"Finished converting: {output_filename}")
        else:
            print(f"Local COPC already exists: {local_output}")

        if not os.path.isfile(local_output):
            print(f"COPC output was not created: {local_output}")
            continue

        if os.path.getsize(local_output) == 0:
            print(f"COPC output is empty: {local_output}")
            continue

        try:
            os.remove(local_input)
        except OSError as error:
            print(f"Could not remove local source {local_input}: {error}")

        future = upload_executor.submit(copy_copc_to_server, local_output, server_output)
        upload_futures[future] = mission

    print()
    print("All conversions submitted. Waiting for remaining uploads...")

    for future in as_completed(upload_futures):
        mission = upload_futures[future]

        try:
            uploaded = future.result()

            if not uploaded:
                print(f"Upload did not complete for: {mission}")

        except Exception as error:
            print(f"Unexpected upload error for {mission}: {error}")

print("Processing finished.")