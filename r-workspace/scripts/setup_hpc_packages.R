#!/usr/bin/env Rscript
# setup_hpc_packages.R — Install nicher + maxentcpp into user R library
#
# Run this ONCE on the HPC cluster inside the Apptainer container:
#   apptainer exec --bind /home/a474r867/R/library:/usr/local/lib/R/site-library \
#     geospatial_latest.sif Rscript setup_hpc_packages.R
#
# Or set R_LIBS_USER and run directly:
#   R_LIBS_USER=~/R/library Rscript setup_hpc_packages.R

cat("[setup] Installing nicher + maxentcpp from GitHub...\n")

lib <- Sys.getenv("R_LIBS_USER", unset = "~/R/library")
dir.create(lib, recursive = TRUE, showWarnings = FALSE)
.libPaths(c(lib, .libPaths()))

if (!requireNamespace("remotes", quietly = TRUE)) {
  install.packages("remotes", repos = "https://cloud.r-project.org", lib = lib)
}

# Dependencies that may not be in geospatial_latest.sif
deps <- c("checkmate", "ucminf", "pomp")
for (pkg in deps) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    cat(sprintf("[setup] Installing dependency: %s\n", pkg))
    install.packages(pkg, repos = "https://cloud.r-project.org", lib = lib)
  }
}

# ucminfcpp (C++ optimizer backend for nicher)
if (!requireNamespace("ucminfcpp", quietly = TRUE)) {
  cat("[setup] Installing ucminfcpp...\n")
  remotes::install_github("alrobles/ucminfcpp", lib = lib, upgrade = "never")
}

# nicher — ellipsoidal ecological niche models
cat("[setup] Installing nicher from GitHub...\n")
remotes::install_github("alrobles/nicher", lib = lib, upgrade = "never", force = TRUE)

# maxentcpp — C++ Maxent implementation
cat("[setup] Installing maxentcpp from GitHub...\n")
remotes::install_github("alrobles/maxentcpp", lib = lib, upgrade = "never", force = TRUE)

cat("[setup] Verifying installations...\n")
stopifnot(requireNamespace("nicher", quietly = TRUE))
stopifnot(requireNamespace("maxentcpp", quietly = TRUE))
cat("[setup] OK — nicher", packageVersion("nicher"), "maxentcpp", packageVersion("maxentcpp"), "\n")
