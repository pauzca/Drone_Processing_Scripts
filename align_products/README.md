# Alignment Scripts

### `align_mission_single.py`

This script aligns a **single target mission** to a **reference mission**. It performs the complete alignment workflow, including:

1. Data preparation (cropping and band separation)
2. Global horizontal alignment
3. Global vertical alignment (DSM)
4. First local alignment
5. Second local alignment
6. Final local vertical alignment (DSM)

The final aligned products are written to the `Product_local2` directory.

---

### `align_missions_globally.py`

This script performs **batch global alignment** for a sequence of missions.

Starting from a user-defined reference mission, it aligns missions chronologically by propagating the alignment both **forward** and **backward** in time. Each mission is aligned to its neighboring mission rather than directly to the original reference, reducing large temporal shifts between consecutive acquisitions.

Currently, this script implements **global alignment only**. Local alignment and vertical refinement are not included.

---

## Installation

Create and activate your environment, then install the required Python packages:

```bash
conda install -c conda-forge numpy pandas matplotlib rasterio geopandas shapely opencv gdal
pip install arosics
```

## Directory Structure

The alignment pipeline creates a working directory containing intermediate products from each processing stage:

```text
Aligned/
├── aux_files/                    # Shapefiles and auxiliary data used during alignment
│
├── Product/                      # Original unaligned products (optional location)
│
├── Product_cropped/              # Cropped inputs used for alignment
│   ├── Orthomosaic/
│   ├── RGB/
│   ├── MS/
│   └── DSM/
│
├── Product_global/               # Results after global alignment
│   ├── COREG_RESULT/             # Global alignment transformation result (.pkl)
│   ├── RGB/
│   ├── MS/
│   └── DSM/
│       └── Vertical_global/      # DSM after vertical correction
│
├── Product_local/                # Results after first local alignment
│   ├── COREG_RESULT/
│   ├── RGB/
│   ├── MS/
│   ├── DSM/
│   └── Orthophoto/
│
└── Product_local2/               # Results after second local alignment
    ├── COREG_RESULT/
    ├── RGB/
    ├── MS/
    ├── DSM/
    │   └── Vertical_local/       # Final vertically corrected DSM
    └── Orthophoto/
```


## Keep in mind:

- The shape in aux_file is used to crop the products to that shape before aligning them. A non rectangular shape will take longer to crop. Areas falling outside of a non rectangular shape will have a value of 0 in an alpah band used for trasnparency.

- This process can take some time and resources. Depending on the size of the raster to be aligned. You will need decent RAM and CPU cores to make this faster

