#!/usr/bin/env Rscript
# niche_pipeline.R — Automated ellipsoidal niche modeling pipeline
#
# Implements the 10-step algorithm:
#   1. Download/read GBIF occurrence points
#   2. Filter unique records
#   3. Remove outliers (IQR on lon/lat)
#   4. Extract ERA5-bioclim at presence points
#   5. Keep unique lon/lat records
#   6. Fit ellipsoid with nicher (presence_only)
#   7. Build M mask: intersect points with ecoregions, keep >5% of points
#   8. Crop ERA5-bioclim with M mask
#   9. Project nicher ellipse on cropped raster
#  10. Write output raster
#
# Usage:
#   Rscript niche_pipeline.R --species "Panthera onca" [options]
#
# Required data paths (reumanlab Toshiba defaults):
#   --bioclim_dir  /media/reumanlab/TOSHIBA_EXT/era5-bioclim
#   --ecoregions   /home/a474r867/work/ecoregions
#   --gbif_parquet /media/reumanlab/TOSHIBA_EXT/gbifdata/occurrence/2026-06-01/occurrence.parquet
#   --output_dir   ./output
#   --bioclim_year 2020

suppressPackageStartupMessages({
  library(terra)
  library(sf)
  library(arrow)
  library(nicher)
})

# ── CLI argument parsing ──────────────────────────────────────────────
parse_args <- function() {
  args <- commandArgs(trailingOnly = TRUE)
  opts <- list(
    species       = NULL,
    bioclim_dir   = "/media/reumanlab/TOSHIBA_EXT/era5-bioclim",
    ecoregions    = "/home/a474r867/work/ecoregions",
    gbif_parquet  = "/media/reumanlab/TOSHIBA_EXT/gbifdata/occurrence/2026-06-01/occurrence.parquet",
    output_dir    = "./output",
    bioclim_vars  = paste0("bio", sprintf("%02d", 1:19)),
    bioclim_year  = 2020L,
    num_starts    = 20L,
    iqr_factor    = 1.5,
    ecoregion_pct = 0.05,
    use_gbif_api  = FALSE,
    gbif_limit    = 50000L
  )

  i <- 1L
  while (i <= length(args)) {
    key <- sub("^--", "", args[i])
    if (key == "chelsa_dir") key <- "bioclim_dir"  # backward compat
    if (key %in% names(opts)) {
      i <- i + 1L
      opts[[key]] <- args[i]
    } else if (key == "help") {
      cat("Usage: Rscript niche_pipeline.R --species \"Genus species\" [options]\n")
      cat("\nOptions:\n")
      cat("  --species        Species name (required)\n")
      cat("  --bioclim_dir    Path to ERA5-bioclim directory\n")
      cat("  --bioclim_year   Year for bioclim data (default: 2020)\n")
      cat("  --ecoregions     Path to ecoregions shapefiles\n")
      cat("  --gbif_parquet   Path to GBIF occurrence parquet\n")
      cat("  --output_dir     Output directory\n")
      cat("  --num_starts     Number of optimizer starts (default: 20)\n")
      cat("  --iqr_factor     IQR multiplier for outlier removal (default: 1.5)\n")
      cat("  --ecoregion_pct  Min fraction of points to keep ecoregion (default: 0.05)\n")
      cat("  --use_gbif_api   If TRUE, query GBIF API instead of parquet\n")
      cat("  --gbif_limit     Max records from GBIF API (default: 50000)\n")
      quit(status = 0)
    }
    i <- i + 1L
  }

  opts$num_starts    <- as.integer(opts$num_starts)
  opts$bioclim_year  <- as.integer(opts$bioclim_year)
  opts$iqr_factor    <- as.numeric(opts$iqr_factor)
  opts$ecoregion_pct <- as.numeric(opts$ecoregion_pct)
  opts$gbif_limit    <- as.integer(opts$gbif_limit)
  opts$use_gbif_api  <- as.logical(opts$use_gbif_api)

  if (is.null(opts$species) || opts$species == "") {
    stop("--species is required. Example: --species \"Panthera onca\"")
  }
  opts
}


# ── Step 1: Get GBIF occurrence points ────────────────────────────────
get_occurrences <- function(species, parquet_path, use_api = FALSE,
                            limit = 50000L) {
  cat(sprintf("[1/10] Getting occurrences for %s...\n", species))

  if (isTRUE(use_api)) {
    if (!requireNamespace("rgbif", quietly = TRUE)) {
      stop("rgbif is required for API queries. Install it first.")
    }
    res <- rgbif::occ_search(
      scientificName = species,
      hasCoordinate  = TRUE,
      limit          = limit,
      fields         = c("species", "decimalLongitude", "decimalLatitude",
                         "year", "basisOfRecord", "coordinateUncertaintyInMeters")
    )
    occ <- res$data
    occ <- occ[!is.na(occ$decimalLongitude) & !is.na(occ$decimalLatitude), ]
  } else {
    cat(sprintf("  Reading parquet: %s\n", parquet_path))
    ds <- arrow::open_dataset(parquet_path)
    occ <- ds |>
      dplyr::filter(species == !!species) |>
      dplyr::select(species, decimalLongitude = decimallongitude,
                    decimalLatitude = decimallatitude) |>
      dplyr::filter(!is.na(decimalLongitude), !is.na(decimalLatitude)) |>
      dplyr::collect()
    occ <- as.data.frame(occ)
  }

  cat(sprintf("  Found %d records\n", nrow(occ)))
  if (nrow(occ) < 10) {
    stop(sprintf("Too few records (%d) for %s. Need at least 10.", nrow(occ), species))
  }
  occ
}


# ── Step 2: Filter unique records ─────────────────────────────────────
filter_unique <- function(occ) {
  cat("[2/10] Filtering unique coordinate records...\n")
  n_before <- nrow(occ)
  occ <- unique(occ[, c("decimalLongitude", "decimalLatitude")])
  names(occ) <- c("lon", "lat")
  cat(sprintf("  %d -> %d unique records\n", n_before, nrow(occ)))
  occ
}


# ── Step 3: Remove outliers (IQR) ────────────────────────────────────
remove_outliers_iqr <- function(occ, factor = 1.5) {
  cat(sprintf("[3/10] Removing outliers (IQR factor=%.1f)...\n", factor))
  n_before <- nrow(occ)

  lon_q <- quantile(occ$lon, c(0.25, 0.75))
  lon_iqr <- diff(lon_q) * factor
  lat_q <- quantile(occ$lat, c(0.25, 0.75))
  lat_iqr <- diff(lat_q) * factor

  keep <- occ$lon >= (lon_q[1] - lon_iqr) & occ$lon <= (lon_q[2] + lon_iqr) &
          occ$lat >= (lat_q[1] - lat_iqr) & occ$lat <= (lat_q[2] + lat_iqr)
  occ <- occ[keep, ]

  cat(sprintf("  %d -> %d records (removed %d outliers)\n",
              n_before, nrow(occ), n_before - nrow(occ)))
  occ
}


# ── Step 4: Extract ERA5-bioclim at presence points ──────────────────
extract_bioclim <- function(occ, bioclim_dir, bioclim_vars, year = 2020L) {
  cat(sprintf("[4/10] Extracting ERA5-bioclim variables (year %d)...\n", year))

  tif_files <- file.path(
    bioclim_dir, as.character(year),
    paste0(bioclim_vars, "_", year, ".tif")
  )
  exists_mask <- file.exists(tif_files)
  if (!any(exists_mask)) {
    stop("No ERA5-bioclim TIF files found in ", file.path(bioclim_dir, year))
  }
  if (!all(exists_mask)) {
    cat(sprintf("  Warning: missing %d TIFs, using %d available\n",
                sum(!exists_mask), sum(exists_mask)))
    cat(sprintf("  Missing: %s\n", paste(basename(tif_files[!exists_mask]), collapse = ", ")))
    tif_files <- tif_files[exists_mask]
    bioclim_vars <- bioclim_vars[exists_mask]
  }

  env_stack <- rast(tif_files)
  names(env_stack) <- bioclim_vars

  pts <- vect(occ, geom = c("lon", "lat"), crs = "EPSG:4326")
  env_vals <- terra::extract(env_stack, pts, ID = FALSE)

  complete <- complete.cases(env_vals)
  occ_env <- cbind(occ[complete, ], env_vals[complete, ])

  cat(sprintf("  Extracted %d variables at %d points (%d had NA, removed)\n",
              length(bioclim_vars), nrow(occ_env), sum(!complete)))
  list(occ = occ_env, vars = bioclim_vars, stack = env_stack)
}


# ── Step 5: Keep unique lon/lat records ──────────────────────────────
deduplicate_coords <- function(occ_env) {
  cat("[5/10] Deduplicating by lon/lat...\n")
  n_before <- nrow(occ_env)
  occ_env <- occ_env[!duplicated(occ_env[, c("lon", "lat")]), ]
  cat(sprintf("  %d -> %d unique coordinate records\n", n_before, nrow(occ_env)))
  occ_env
}


# ── Step 6: Fit nicher ellipsoid (presence_only) ─────────────────────
fit_nicher_ellipsoid <- function(occ_env, bioclim_vars, num_starts = 20L) {
  cat(sprintf("[6/10] Fitting nicher ellipsoid (presence_only, %d starts)...\n",
              num_starts))

  env_occ <- as.data.frame(occ_env[, bioclim_vars])

  fit <- optimize_niche(
    env_occ    = env_occ,
    likelihood = "presence_only",
    num_starts = num_starts
  )

  cat(sprintf("  Best neg-loglik: %.2f\n", fit$best$value))
  cat(sprintf("  Convergence: %d\n", fit$best$conv))
  fit
}


# ── Step 7: Build M mask from ecoregions ─────────────────────────────
build_m_mask <- function(occ_filtered, ecoregions_dir, ecoregion_pct = 0.05) {
  cat(sprintf("[7/10] Building M mask (ecoregion threshold=%.0f%%)...\n",
              ecoregion_pct * 100))

  # Find the shapefile
  shp_files <- list.files(ecoregions_dir, pattern = "\\.shp$",
                          full.names = TRUE, recursive = TRUE)
  if (length(shp_files) == 0) {
    stop("No .shp files found in ", ecoregions_dir)
  }
  cat(sprintf("  Using ecoregion shapefile: %s\n", basename(shp_files[1])))
  ecoregions <- st_read(shp_files[1], quiet = TRUE)

  # Convert points to sf
  pts_sf <- st_as_sf(occ_filtered, coords = c("lon", "lat"), crs = 4326)

  # Ensure same CRS
  if (st_crs(ecoregions) != st_crs(pts_sf)) {
    ecoregions <- st_transform(ecoregions, crs = 4326)
  }

  # Intersect points with ecoregions
  intersection <- st_join(pts_sf, ecoregions, join = st_within)

  # Find the ecoregion ID column (try common names)
  eco_id_col <- NULL
  candidates <- c("ECO_NAME", "ECO_ID", "eco_name", "eco_id",
                   "BIOME_NAME", "BIOME", "NAME", "name", "OBJECTID")
  for (cand in candidates) {
    if (cand %in% names(intersection)) {
      eco_id_col <- cand
      break
    }
  }
  if (is.null(eco_id_col)) {
    # Use the first non-geometry character column
    chr_cols <- names(intersection)[vapply(st_drop_geometry(intersection),
                                           is.character, logical(1))]
    if (length(chr_cols) > 0) eco_id_col <- chr_cols[1]
  }
  if (is.null(eco_id_col)) {
    stop("Cannot find ecoregion identifier column in shapefile")
  }
  cat(sprintf("  Ecoregion ID column: %s\n", eco_id_col))

  # Count points per ecoregion
  eco_counts <- table(st_drop_geometry(intersection)[[eco_id_col]])
  total_pts <- nrow(occ_filtered)
  eco_pct <- eco_counts / total_pts

  # Keep ecoregions with >threshold% of points
  keep_ecos <- names(eco_pct[eco_pct >= ecoregion_pct])
  cat(sprintf("  %d ecoregions total, %d with >= %.0f%% of points\n",
              length(eco_pct), length(keep_ecos), ecoregion_pct * 100))

  if (length(keep_ecos) == 0) {
    cat("  Warning: no ecoregions pass threshold, using all with any points\n")
    keep_ecos <- names(eco_pct[eco_pct > 0])
  }

  # Subset and dissolve ecoregions into M mask
  m_mask <- ecoregions[ecoregions[[eco_id_col]] %in% keep_ecos, ]
  m_mask <- st_union(m_mask)

  cat(sprintf("  M mask covers %d ecoregion(s)\n", length(keep_ecos)))
  m_mask
}


# ── Step 8: Crop bioclim rasters with M mask ─────────────────────────
crop_bioclim_with_mask <- function(env_stack, m_mask) {
  cat("[8/10] Cropping ERA5-bioclim with M mask...\n")

  m_vect <- vect(m_mask)
  env_cropped <- crop(env_stack, m_vect)
  env_masked <- mask(env_cropped, m_vect)

  cat(sprintf("  Cropped raster: %d x %d cells, %d layers\n",
              nrow(env_masked), ncol(env_masked), nlyr(env_masked)))
  env_masked
}


# ── Step 9: Project nicher ellipse onto cropped raster ───────────────
project_nicher <- function(fit, env_masked, output_path) {
  cat("[9/10] Projecting nicher ellipsoid onto cropped raster...\n")

  suit <- predict(fit, env_masked, output = output_path, overwrite = TRUE)

  vals <- values(suit, na.rm = TRUE)
  cat(sprintf("  Suitability range: [%.4f, %.4f]\n", min(vals), max(vals)))
  cat(sprintf("  Non-NA cells: %d\n", length(vals)))
  suit
}


# ── Step 10: Write outputs ───────────────────────────────────────────
write_outputs <- function(suit, fit, occ_env, species, output_dir) {
  cat("[10/10] Writing outputs...\n")
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

  species_clean <- gsub("[^a-zA-Z0-9]", "_", species)

  # Suitability raster (already written in step 9 if output_path was set)
  raster_path <- file.path(output_dir, paste0(species_clean, "_suitability.tif"))
  if (!file.exists(raster_path)) {
    writeRaster(suit, raster_path, overwrite = TRUE)
  }
  cat(sprintf("  Raster: %s\n", raster_path))

  # Ellipsoid parameters
  pars <- get_ellipsoid_pars(occ_env[, fit$var_names])
  pars_path <- file.path(output_dir, paste0(species_clean, "_ellipsoid_params.rds"))
  saveRDS(list(
    mu       = pars$mu,
    sigma    = pars$s_mat,
    fit      = fit,
    species  = species,
    n_points = nrow(occ_env),
    vars     = fit$var_names
  ), pars_path)
  cat(sprintf("  Parameters: %s\n", pars_path))

  # Filtered occurrence points
  occ_path <- file.path(output_dir, paste0(species_clean, "_occurrences.csv"))
  write.csv(occ_env, occ_path, row.names = FALSE)
  cat(sprintf("  Occurrences: %s\n", occ_path))

  # Summary
  summary_path <- file.path(output_dir, paste0(species_clean, "_summary.txt"))
  sink(summary_path)
  cat("=== Niche Model Summary ===\n")
  cat(sprintf("Species: %s\n", species))
  cat(sprintf("N points (filtered): %d\n", nrow(occ_env)))
  cat(sprintf("Variables: %s\n", paste(fit$var_names, collapse = ", ")))
  cat(sprintf("Likelihood: %s\n", fit$likelihood))
  cat(sprintf("Neg-loglik: %.4f\n", fit$best$value))
  cat(sprintf("Convergence: %d\n", fit$best$conv))
  cat("\nCentroid (mu):\n")
  print(pars$mu)
  cat("\nCovariance (Sigma):\n")
  print(pars$s_mat)
  sink()
  cat(sprintf("  Summary: %s\n", summary_path))

  cat("\n=== Pipeline complete ===\n")
  invisible(list(
    raster_path  = raster_path,
    params_path  = pars_path,
    occ_path     = occ_path,
    summary_path = summary_path
  ))
}


# ── Main pipeline ────────────────────────────────────────────────────
main <- function() {
  opts <- parse_args()
  cat(sprintf("\n=== Niche Pipeline: %s ===\n\n", opts$species))

  # Step 1: Get occurrences
  occ <- get_occurrences(opts$species, opts$gbif_parquet,
                         opts$use_gbif_api, opts$gbif_limit)

  # Step 2: Filter unique records
  occ <- filter_unique(occ)

  # Step 3: Remove outliers
  occ <- remove_outliers_iqr(occ, opts$iqr_factor)

  # Step 4: Extract bioclim
  bioclim_vars <- strsplit(opts$bioclim_vars, ",")[[1]]
  if (length(bioclim_vars) == 1 && grepl(" ", bioclim_vars)) {
    bioclim_vars <- strsplit(bioclim_vars, "\\s+")[[1]]
  }
  result <- extract_bioclim(occ, opts$bioclim_dir, bioclim_vars, opts$bioclim_year)
  occ_env <- result$occ
  bioclim_vars <- result$vars
  env_stack <- result$stack

  # Step 5: Deduplicate
  occ_env <- deduplicate_coords(occ_env)

  # Step 6: Fit nicher ellipsoid
  fit <- fit_nicher_ellipsoid(occ_env, bioclim_vars, opts$num_starts)

  # Step 7: Build M mask
  m_mask <- build_m_mask(occ[, c("lon", "lat")], opts$ecoregions,
                         opts$ecoregion_pct)

  # Step 8: Crop bioclim
  env_masked <- crop_bioclim_with_mask(env_stack, m_mask)

  # Step 9: Project
  species_clean <- gsub("[^a-zA-Z0-9]", "_", opts$species)
  output_raster <- file.path(opts$output_dir,
                             paste0(species_clean, "_suitability.tif"))
  dir.create(opts$output_dir, recursive = TRUE, showWarnings = FALSE)
  suit <- project_nicher(fit, env_masked, output_raster)

  # Step 10: Write outputs
  write_outputs(suit, fit, occ_env, opts$species, opts$output_dir)
}


# ── Entry point ──────────────────────────────────────────────────────
if (!interactive()) {
  main()
}
