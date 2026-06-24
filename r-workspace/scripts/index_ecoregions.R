#!/usr/bin/env Rscript
# index_ecoregions.R — Pre-process Ecoregions2017.shp for fast loading
#
# Saves validated/simplified sf object as RDS (binary R format).
# Loads in ~2-5s vs 30s+ from shapefile on USB.
#
# Usage:
#   Rscript index_ecoregions.R [--shp_dir /path/to/ecoregions]
#
# Default: /media/reumanlab/TOSHIBA_EXT/ecoregions

suppressPackageStartupMessages({
  library(sf)
})

args <- commandArgs(trailingOnly = TRUE)
shp_dir <- "/media/reumanlab/TOSHIBA_EXT/ecoregions"

i <- 1L
while (i <= length(args)) {
  if (args[i] == "--shp_dir" && i < length(args)) {
    shp_dir <- args[i + 1L]; i <- i + 2L
  } else {
    i <- i + 1L
  }
}

shp_path <- file.path(shp_dir, "Ecoregions2017.shp")
rds_path <- file.path(shp_dir, "ecoregions.rds")

if (!file.exists(shp_path)) {
  shp_candidates <- list.files(shp_dir, pattern = "\\.shp$",
                                full.names = TRUE, recursive = TRUE)
  if (length(shp_candidates) == 0) stop("No .shp files found in ", shp_dir)
  shp_path <- shp_candidates[1]
}

cat(sprintf("=== Indexing Ecoregions → RDS ===\n"))
cat(sprintf("  Shapefile: %s\n", shp_path))
cat(sprintf("  Output:    %s\n", rds_path))

# Load shapefile
cat("  Loading shapefile...\n")
t0 <- proc.time()[3]
old_s2 <- sf::sf_use_s2()
sf::sf_use_s2(FALSE)
eco <- sf::st_read(shp_path, quiet = TRUE)
dt_load <- proc.time()[3] - t0
cat(sprintf("  Loaded %d ecoregion polygons in %.1fs\n", nrow(eco), dt_load))

# Validate and fix geometries
cat("  Validating geometries...\n")
t0 <- proc.time()[3]
eco <- sf::st_make_valid(eco)
if (!identical(sf::st_crs(eco)$epsg, 4326L)) {
  eco <- sf::st_transform(eco, 4326)
}
dt_valid <- proc.time()[3] - t0
cat(sprintf("  Validated in %.1fs\n", dt_valid))

# Keep only essential columns
keep_cols <- intersect(c("ECO_NAME", "ECO_ID", "BIOME_NUM", "BIOME_NAME",
                          "REALM", "NNH", "SHAPE_AREA"), names(eco))
if (!"ECO_NAME" %in% keep_cols) {
  keep_cols <- c(names(eco)[1], keep_cols)
}
geo_col <- attr(eco, "sf_column")
eco_slim <- eco[, c(keep_cols, geo_col)]

# Simplify geometry to reduce file size (tolerance ~100m, preserves topology)
cat("  Simplifying geometry (100m tolerance)...\n")
t0 <- proc.time()[3]
eco_slim <- sf::st_simplify(eco_slim, dTolerance = 0.001, preserveTopology = TRUE)
dt_simp <- proc.time()[3] - t0
cat(sprintf("  Simplified in %.1fs\n", dt_simp))

sf::sf_use_s2(old_s2)

# Save as RDS
cat("  Saving as RDS...\n")
t0 <- proc.time()[3]
saveRDS(eco_slim, rds_path)
dt_save <- proc.time()[3] - t0

rds_size <- file.info(rds_path)$size / 1024 / 1024
cat(sprintf("  Saved in %.1fs (%.1f MB)\n", dt_save, rds_size))

# Test loading speed
cat("  Testing load speed...\n")
t0 <- proc.time()[3]
eco_test <- readRDS(rds_path)
dt_read <- proc.time()[3] - t0
cat(sprintf("  RDS load: %.1fs (vs %.1fs for shapefile)\n", dt_read, dt_load))
cat(sprintf("  Speedup: %.0fx\n", dt_load / max(dt_read, 0.01)))

# Test spatial query
pts <- sf::st_sfc(sf::st_point(c(0.0, 51.5)), crs = 4326)
sf::sf_use_s2(FALSE)
hit <- sf::st_intersects(pts, eco_test, sparse = TRUE)
sf::sf_use_s2(old_s2)
if (length(hit[[1]]) > 0) {
  cat(sprintf("  Test query (lon=0, lat=51.5): %s\n", eco_test$ECO_NAME[hit[[1]][1]]))
} else {
  cat("  Test query: no intersection (point in ocean)\n")
}

cat(sprintf("\n=== Done! %s (%.1f MB) ===\n", rds_path, rds_size))
cat("Pipeline will auto-detect this RDS and skip shapefile loading.\n")
