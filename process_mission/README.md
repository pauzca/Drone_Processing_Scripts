# Process missions

After flying the drone you might want to create an orthomosaic, dsm and pointcloud. To do so you can process the images in a Photogrametry software such as Agisoft Metashape to stitch all the images together. 

You will need an Agisoft Metashape Licence to run this script.

## Setup

First you need to have miniconda or anaconda installed. Or install it here https://www.anaconda.com/docs/getting-started/installation
The first time you use this repository, create the Conda environment and install the required dependencies.


#### 1. Create the environment
 
> **Note:** The Metashape installation is only required for the scripts in `process_mission/`. It is **not** needed to run the scripts in `align_products/`, `cloud_optimized/`, or `experiments/`.


I recommend creating the enviroment as it is pointed out here because otherwise you might have problems with pdal installation

```bash
conda create -n dronerun -c conda-forge python=3.11 pdal --solver=libmamba
```

#### 2. Activate the environment

```bash
conda activate dronerun
```

#### 3. Install the remaining dependencies

```bash
conda install -c conda-forge gdal
conda install pip
python -m pip install pandas
```

#### 4. Install the Agisoft Metashape Python module

Download the **Metashape Professional Python Module** for **Windows** from the Agisoft website:

https://www.agisoft.com/downloads/installer/

Navigate to:

> **Python 3 Module → Windows**

Then install the downloaded wheel file:

```bash
python -m pip install "path/to/Metashape-<version>.whl"
```

For example:

```bash
python -m pip install "C:\Downloads\Metashape-2.2.2-cp311-cp311-win_amd64.whl"
```

#### 5. Verify the installation (optional)

```bash
python --version
pdal --version
gdalinfo --version
```

If all commands return version numbers without errors, the environment is ready to use.

---

### Running the Scripts

Each time you open a new terminal, activate the Conda environment before running any scripts:

```bash
conda activate dronerun
```

Then to run any script:

```bash
python name_of_script.py
```


# Trinity_process

Run `trinity_process_many.py` to process multiple missions from a given year.

`trinity_process_single.py` will do the same thing but you need to change the script directly. I left this here to make it easier to modify or debug the script. 


When the script starts, it will prompt you to enter the **year** (e.g., `2024`). It will then search the corresponding directory in the `Raw` folder and prompt you to select the misssion to be processed:

```text
Raw/
└── <year>/
    ├── <Mission_1>/
    │   └── Images/
    ├── <Mission_2>/
    │   └── Images/
    └── ...
```

Each subdirectory under `Raw/<year>/` is assumed to contain a single mission, and the folder name is used as the mission name. All the trinity flights should already have corrected GPS coordinates. 

**Requirements**

- The `Images/` folder must contain all images for a single mission.
- Image coordinates **must already be corrected using the antenna (PPK/RTK processing)** before running the processing scripts.
- Each mission should be stored in its own folder under the corresponding acquisition year.


## Output Directory Structure

After processing, each mission is organized as follows:

```text
Products/
└── <year>/
    └── <Mission_Name>/
        ├── Project/
        │   ├── <Mission_Name>_medium.psx          # Metashape project
        │   ├── <Mission_Name>_medium.files/       # Metashape project data
        │   └── <Mission_Name>_report.pdf          # Processing report
        │
        ├── Orthophoto/
        │   ├── <Mission_Name>_orthomosaic.tif     # Orthomosaic
        │   └── <Mission_Name>_orthomosaic.cog.tif # Cloud Optimized GeoTIFF (COG)
        │
        ├── Cloudpoint/
        │   ├── <Mission_Name>_cloud.las           # Point cloud
        │   └── <Mission_Name>.copc.laz            # Cloud Optimized Point Cloud (COPC)
        │
        └── DSM/
            ├── <Mission_Name>_dsm.tif             # Digital Surface Model
            └── <Mission_Name>_dsm.cog.tif         # Cloud Optimized GeoTIFF (COG)
```

# Mavic_process

Run `mavic_process_many.py` to process multiple missions Multispectral Mavic missions in a given year. 

It works the same as trinity_process_many but for multispectral images. The expected input directory structure should be:

```text
Raw/
└── <year>/
    ├── <Mission_1>/
    │   ├── flight1/
    │   │   ├── Georeference/
    │   │   │   └── tagged_RGB/
    │   │   │       ├── img000_D.jpg
    │   │   │       ├── img001_D.jpg
    │   │   │       └── ...
    │   │   └── Multispectral/
    │   │       ├── img000_MS_G.jpg
    │   │       ├── img000_MS_R.jpg
    │   │       ├── img000_MS_RE.jpg
    │   │       ├── img000_MS_NIR.jpg
    │   │       └── ...
    │   ├── flight2/
    │   │   ├── Georeference/
    │   │   │   └── tagged_RGB/
    │   │   │       ├── img100_D.jpg
    │   │   │       └── ...
    │   │   └── Multispectral/
    │   │       ├── img100_MS_G.jpg
    │   │       ├── img100_MS_R.jpg
    │   │       ├── img100_MS_RE.jpg
    │   │       ├── img100_MS_NIR.jpg
    │   │       └── ...
    │   └── ...
    └── ...
```

Either have the same structure or modify the code to work with the way you store your multispectral images :)

# Finsih mission run

If the scripts for some reason does not finish running you can use `finish_mission_run.py` to finish the mission and not having to reprocess it again. To do this, open the agisoft project and see what step were finished. Comment the steps that have been finished in this script and run it. 



