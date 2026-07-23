## Drone scripts

This repository contains scripts for processing raw drone missions obtaning DSM, Pointcloud and Orthomosaic products. 
Also scripts to align the drone missions. And scripts to convert them to cloud optimized formats.


## Repository Structure

```text
drone_scripts/
├── align_products/                   # Align drone products through time
│   ├── align_missions_globally.py    # Globally align multiple missions departing from a reference orthomosaic
│   ├── align_mission_single.py       # Align a single mission to a reference, globally and locally
│   └── raster_tools_ms.py            # Raster processing utilities
│
├── cloud_optimized/                  # Helper scripts to convert to cloud optimized format
│   ├── convert_cog.py                # Convert GeoTIFFs to Cloud Optimized GeoTIFFs (COG)
│   └── convert_copc.py               # Convert LAS point clouds to Cloud Optimized PointClouds (COPC)
│
├── experiments/                      # Things I tried out or incomplete scripts
│   ├── check_alignment.ipynb         # Notebook were I tried to estimate alignment quality between drone products using the DSM's
│   ├── create_timeseries.ipynb       # Time-series generation of a patch of orthomosaic. This works for qualitatively assess temporal alignment
│   └── mavic_process_chunking.py     # Test of drone image processing pipeline to optimize memory
│
├── process_mission/                  # Generate orthomosaic and other products from Raw drone imagery
│   ├── finish_mission_run.py         # Finalize an interrupted drone processing workflow
│   ├── mavic_process_many.py         # Process multiple Mavic Multispectral missions
│   ├── trinity_process_many.py       # Process multiple Trinity missions
│   └── trinity_process_single.py     # Process a single Trinity mission
│
└── README.md
```

You will find detailed readmes in each folder. 


## Advice for processing drone images

Here I will list some lessons I learned about processing drone images during my internship:

- Always save the reports in PDF of the processing in Metashape

- Make sure you have enough disk space and RAM to run the processing. Metashape needs a lot of temporary disk space (at least 500GB for big missions). And the alignment scripts needs more than 32GB of RAM available. This depends on the size of the mission (area covered and size of images, multispectral images are a lot heavier than RGB).

- If possible use an antenna to correct the coordinates of the images. This means having PPK or RTK antenna at the moment of the flight. Although I think PPK tends to be more stable. Make sure Metashape is using the antenna coordinates correctly. Check that the Accuracy of the images is in the centimeter scale. By default image accuracy is set to 10m, which is fine for coordinates coming from the GPS only. For geocorrected coordinates the accuracy should be much better > 1cm. 

- Always save the Orthomosaic, DSM and Pointcloud in Cloud Optimized format, it makes it much faster for visualization. And this is the format you'll want to share with other people.

- Don't delete intermediate files (such as the Metashape project) until you are sure the products are good quality and the processing went well. I recommend keeping them until the data has been published if possible. Don't delete the raw images if possible.



## TODO

- The alignment pipeline works for the DSM and Orthomosaic but I have not implemented alignment of the Pointclouds.  I still have not used pointclouds in any project, but could be worth exploring in the future. 




## About me

These script were written by me, Paula Uzcátegui León, during my internship at the Quantitative Ecology Lab at the Smithsonian Tropical Research Institude in Gamboa, Panamá (February - July 2026). I used these script to process over 100 drone missions for the data publication at <INSERT URL>. The majority of this code was adapted from the code written by Vicente Vasquez https://github.com/VasquezVicente/ForestLandscapes/tree/main/LandscapeScripts

You can find updates of these scripts in my repository https://github.com/pauzca/Drone_Processing_Scripts
