#!/usr/bin/env Rscript
# niche_pipeline.R — Automated ellipsoidal niche modeling pipeline
#
# Implements the 10-step algorithm (Barve et al. 2011 compliant):
#   1. Download/read GBIF occurrence points
#   2. Filter unique records
#   3. Remove geographic outliers (IQR on lon/lat)
#   4. Extract ERA5-bioclim at presence points
#   5. Deduplicate coordinates
#   6. Environmental IQR filtering (remove bioclim outliers)
#   7. Build M mask: intersect points with ecoregions, dissolve to M polygon
#   8. Crop ERA5-bioclim with M mask
#   9. Fit nicher ellipsoid (presence_only) with M-filtered env data
#  10. Project nicher ellipse on M-cropped raster + write outputs
#
# Key scientific references:
#   - Barve et al. 2011. Ecological Modelling 222: 1810-1819 (M mask)
#   - Soberon & Peterson 2005. Biodiversity Informatics 2: 1-10 (BAM)
#
# Usage:
#   Rscript niche_pipeline.R --species "Panthera onca" [options]
#
# Required data paths (reumanlab Toshiba defaults):
#   --bioclim_dir  /media/reumanlab/TOSHIBA_EXT/era5-bioclim
#   --ecoregions   /media/reumanlab/TOSHIBA_EXT/ecoregions
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
    species        = NULL,
    bioclim_dir    = "/media/reumanlab/TOSHIBA_EXT/era5-bioclim",
    ecoregions     = "/media/reumanlab/TOSHIBA_EXT/ecoregions",
    gbif_parquet   = "/media/reumanlab/TOSHIBA_EXT/gbifdata/occurrence/2026-06-01/occurrence.parquet",
    output_dir     = "./output",
    bioclim_vars   = paste0("bio", sprintf("%02d", 1:19)),
    bioclim_year   = 2020L,
    num_starts     = 20L,
    iqr_factor     = 1.5,
    env_iqr_factor = 1.5,
    ecoregion_pct  = 0.05,
    use_gbif_api   = FALSE,
    gbif_limit     = 50000L
  )

  i <- 1L
  while (i <= length(args)) {
    key <- sub("^--", "", args[i])
    if (key == "chelsa_dir") key <- "bioclim_dir"
    if (key %in% names(opts)) {
      i <- i + 1L
      opts[[key]] <- args[i]
    } else if (key == "help") {
      cat("Usage: Rscript niche_pipeline.R --species \"Genus species\" [options]\n")
      cat("\nOptions:\n")
      cat("  --species         Species name (required)\n")
      cat("  --bioclim_dir     Path to ERA5-bioclim directory\n")
      cat("  --bioclim_year    Year for bioclim data (default: 2020)\n")
      cat("  --ecoregions      Path to ecoregions shapefiles\n")
      cat("  --gbif_parquet    Path to GBIF occurrence parquet\n")
      cat("  --output_dir      Output directory\n")
      cat("  --num_starts      Number of optimizer starts (default: 20)\n")
      cat("  --iqr_factor      IQR multiplier for geographic outlier removal (default: 1.5)\n")
      cat("  --env_iqr_factor  IQR multiplier for environmental outlier removal (default: 1.5)\n")
      cat("  --ecoregion_pct   Min fraction of points to keep ecoregion (default: 0.05)\n")
      cat("  --use_gbif_api    If TRUE, query GBIF API instead of parquet\n")
      cat("  --gbif_limit      Max records from GBIF API (default: 50000)\n")
      quit(status = 0)
    }
    i <- i + 1L
  }

  opts$num_starts     <- as.integer(opts$num_starts)
  opts$bioclim_year   <- as.integer(opts$bioclim_year)
  opts$iqr_factor     <- as.numeric(opts$iqr_factor)
  opts$env_iqr_factor <- as.numeric(opts$env_iqr_factor)
  opts$ecoregion_pct  <- as.numeric(opts$ecoregion_pct)
  opts$gbif_limit     <- as.integer(opts$gbif_limit)
  opts$use_gbif_api   <- as.logical(opts$use_gbif_api)

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


# ── Step 3: Remove geographic outliers (IQR on coordinates) ──────────
remove_outliers_iqr <- function(occ, factor = 1.5) {
  cat(sprintf("[3/10] Removing geographic outliers (IQR factor=%.1f)...\n", factor))
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


# ── Step 5: Deduplicate coordinates ──────────────────────────────────
deduplicate_coords <- function(occ_env) {
  cat("[5/10] Deduplicating by lon/lat...\n")
  n_before <- nrow(occ_env)
  occ_env <- occ_env[!duplicated(occ_env[, c("lon", "lat")]), ]
  cat(sprintf("  %d -> %d unique coordinate records\n", n_before, nrow(occ_env)))
  occ_env
}


# ── Step 6: Environmental IQR filtering ──────────────────────────────
# Removes presence points with bioclim values outside the IQR range
# for ANY variable. Eliminates environmental noise from georeferencing
# errors and vagrant individuals.
filter_env_iqr <- function(occ_env, bioclim_vars, env_iqr_factor = 1.5) {
  cat(sprintf("[6/10] Environmental IQR filtering (factor=%.1f)...\n",
              env_iqr_factor))
  n_before <- nrow(occ_env)

  outlier_flag <- rep(FALSE, nrow(occ_env))
  for (v in bioclim_vars) {
    x <- occ_env[[v]]
    q1 <- quantile(x, 0.25, na.rm = TRUE)
    q3 <- quantile(x, 0.75, na.rm = TRUE)
    iqr_val <- q3 - q1
    lower <- q1 - env_iqr_factor * iqr_val
    upper <- q3 + env_iqr_factor * iqr_val
    outlier_flag <- outlier_flag | (x < lower | x > upper)
  }

  occ_env <- occ_env[!outlier_flag, ]
  cat(sprintf("  %d -> %d after environmental IQR filtering (%d removed)\n",
              n_before, nrow(occ_env), n_before - nrow(occ_env)))
  if (nrow(occ_env) < 10) stop("Too few points after environmental IQR filtering")
  occ_env
}


# ── Step 7: Build M mask from ecoregions (Barve et al. 2011) ─────────
# Uses pre-indexed RDS when available (~2s load vs ~30s+ for shapefile).
# Falls back to shapefile with bbox filter (slower).
build_m_mask <- function(occ_filtered, ecoregions_dir, ecoregion_pct = 0.05) {
  cat(sprintf("[7/10] Building M mask (ecoregion threshold=%.0f%%)...\n",
              ecoregion_pct * 100))

  old_s2 <- sf::sf_use_s2()
  sf::sf_use_s2(FALSE)
  on.exit(sf::sf_use_s2(old_s2))

  rds_path <- file.path(ecoregions_dir, "ecoregions.rds")
  if (file.exists(rds_path)) {
    cat(sprintf("  Using pre-indexed RDS: %s\n", basename(rds_path)))
    build_m_mask_rds_niche(occ_filtered, rds_path, ecoregion_pct)
  } else {
    cat("  RDS not found, falling back to shapefile...\n")
    build_m_mask_shapefile_niche(occ_filtered, ecoregions_dir, ecoregion_pct)
  }
}

build_m_mask_rds_niche <- function(occ_filtered, rds_path, ecoregion_pct = 0.05) {
  t0 <- proc.time()[3]
  eco <- readRDS(rds_path)
  dt_load <- proc.time()[3] - t0
  cat(sprintf("  Loaded %d ecoregions from RDS in %.1fs\n", nrow(eco), dt_load))

  eco <- sf::st_make_valid(eco)
  pts_sf <- sf::st_as_sf(occ_filtered, coords = c("lon", "lat"), crs = 4326)

  t0 <- proc.time()[3]
  join <- sf::st_join(pts_sf, eco, join = sf::st_intersects)
  dt_join <- proc.time()[3] - t0
  cat(sprintf("  Spatial join: %d matches in %.1fs\n",
              sum(!is.na(join$ECO_NAME)), dt_join))

  join <- join[!is.na(join$ECO_NAME), ]
  if (nrow(join) == 0) {
    cat("  Warning: no points matched ecoregions, using convex hull\n")
    hull <- sf::st_buffer(sf::st_convex_hull(sf::st_union(pts_sf)), dist = 2)
    return(hull)
  }

  freq <- table(join$ECO_NAME)
  keep <- names(freq[freq >= max(1, ceiling(nrow(occ_filtered) * ecoregion_pct))])
  if (length(keep) == 0) keep <- names(freq[freq > 0])
  cat(sprintf("  %d ecoregions selected (of %d with points)\n",
              length(keep), length(freq)))

  m_eco <- eco[eco$ECO_NAME %in% keep, ]
  m_poly <- sf::st_make_valid(sf::st_union(m_eco))
  cat(sprintf("  M mask built from %d ecoregion(s)\n", length(keep)))
  m_poly
}

build_m_mask_shapefile_niche <- function(occ_filtered, ecoregions_dir, ecoregion_pct = 0.05) {
  shp_path <- file.path(ecoregions_dir, "Ecoregions2017.shp")
  if (!file.exists(shp_path)) {
    shp_files <- list.files(ecoregions_dir, pattern = "\\.shp$",
                            full.names = TRUE, recursive = TRUE)
    if (length(shp_files) == 0) stop("No .shp files found in ", ecoregions_dir)
    shp_path <- shp_files[1]
  }

  pts_sf <- st_as_sf(occ_filtered, coords = c("lon", "lat"), crs = 4326)
  bbox <- st_bbox(pts_sf)
  bbox_buf <- st_bbox(c(
    xmin = max(bbox["xmin"] - 5, -180),
    ymin = max(bbox["ymin"] - 5, -90),
    xmax = min(bbox["xmax"] + 5, 180),
    ymax = min(bbox["ymax"] + 5, 90)
  ), crs = st_crs(4326))
  wkt_filter <- st_as_text(st_as_sfc(bbox_buf))

  ecoregions <- st_read(shp_path, wkt_filter = wkt_filter, quiet = TRUE)
  if (nrow(ecoregions) == 0) ecoregions <- st_read(shp_path, quiet = TRUE)
  ecoregions <- st_make_valid(ecoregions)
  if (!identical(st_crs(ecoregions)$epsg, 4326L)) {
    ecoregions <- st_transform(ecoregions, crs = 4326)
  }

  intersection <- st_join(pts_sf, ecoregions, join = st_intersects)
  eco_id_col <- NULL
  for (cand in c("ECO_NAME", "ECO_ID", "eco_name", "eco_id")) {
    if (cand %in% names(intersection)) { eco_id_col <- cand; break }
  }
  if (is.null(eco_id_col)) {
    chr_cols <- names(intersection)[vapply(st_drop_geometry(intersection),
                                           is.character, logical(1))]
    if (length(chr_cols) > 0) eco_id_col <- chr_cols[1]
  }
  if (is.null(eco_id_col)) stop("Cannot find ecoregion ID column")
  intersection <- intersection[!is.na(intersection[[eco_id_col]]), ]

  freq <- table(st_drop_geometry(intersection)[[eco_id_col]])
  keep <- names(freq[freq >= max(1, ceiling(nrow(occ_filtered) * ecoregion_pct))])
  if (length(keep) == 0) keep <- names(freq[freq > 0])

  m_mask <- ecoregions[ecoregions[[eco_id_col]] %in% keep, ]
  st_make_valid(st_union(m_mask))
}


# ── Step 8: Crop bioclim rasters with M mask ─────────────────────────
crop_bioclim_with_mask <- function(env_stack, m_mask) {
  cat("[8/10] Cropping ERA5-bioclim with M mask...\n")

  m_vect <- vect(m_mask)
  env_cropped <- crop(env_stack, m_vect)
  env_masked <- mask(env_cropped, m_vect)

  n_valid <- sum(!is.na(values(env_masked[[1]])))
  cat(sprintf("  Cropped raster: %d x %d cells, %d layers\n",
              nrow(env_masked), ncol(env_masked), nlyr(env_masked)))
  cat(sprintf("  Valid cells in M: %d\n", n_valid))
  env_masked
}


# ── Step 9: Fit nicher ellipsoid (presence_only) ─────────────────────
# Fitted with environmental data from M-filtered presence points.
fit_nicher_ellipsoid <- function(occ_env, bioclim_vars, num_starts = 20L) {
  cat(sprintf("[9/10] Fitting nicher ellipsoid (presence_only, %d starts)...\n",
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


# ── Step 10: Project + write outputs ─────────────────────────────────
project_and_write <- function(fit, env_masked, occ_env, species, output_dir) {
  cat("[10/10] Projecting ellipsoid and writing outputs...\n")
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

  species_clean <- gsub("[^a-zA-Z0-9]", "_", species)

  # Project nicher ellipsoid onto M-cropped rasters
  raster_path <- file.path(output_dir, paste0(species_clean, "_suitability.tif"))
  suit <- predict(fit, env_masked, output = raster_path, overwrite = TRUE)

  vals <- values(suit, na.rm = TRUE)
  cat(sprintf("  Suitability range: [%.4f, %.4f]\n", min(vals), max(vals)))
  cat(sprintf("  Non-NA cells: %d\n", length(vals)))

  # Suitability PNG
  png_path <- file.path(output_dir, paste0(species_clean, "_suitability.png"))
  grDevices::png(png_path, width = 1000, height = 700, res = 120)
  suit_cols <- grDevices::colorRampPalette(
    c("#2166AC", "#67A9CF", "#D1E5F0", "#FDDBC7", "#EF8A62", "#B2182B")
  )(100)
  terra::plot(suit, col = suit_cols, range = c(0, 1),
              main = paste0(species, "\nNicher ellipsoidal suitability (M-restricted)"),
              plg = list(title = "Suitability", title.cex = 0.8),
              mar = c(3, 3, 3, 5))
  if (nrow(occ_env) > 0) {
    lon_col <- if ("decimalLongitude" %in% names(occ_env)) "decimalLongitude" else "lon"
    lat_col <- if ("decimalLatitude" %in% names(occ_env)) "decimalLatitude" else "lat"
    graphics::points(occ_env[[lon_col]], occ_env[[lat_col]],
                     pch = 16, cex = 0.4, col = grDevices::adjustcolor("black", 0.5))
  }
  grDevices::dev.off()
  cat(sprintf("  PNG: %s\n", png_path))

  # Ellipsoid parameters
  pars <- get_ellipsoid_pars(occ_env[, fit$var_names])
  pars_path <- file.path(output_dir, paste0(species_clean, "_ellipsoid_params.rds"))
  saveRDS(list(
    mu       = pars$mu,
    sigma    = pars$s_mat,
    fit      = fit,
    species  = species,
    n_points = nrow(occ_env),
    vars     = fit$var_names,
    m_mask   = "ecoregion"
  ), pars_path)
  cat(sprintf("  Parameters: %s\n", pars_path))

  # Filtered occurrences
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
  cat(sprintf("M mask: ecoregion-based (Barve et al. 2011)\n"))
  cat("\nCentroid (mu):\n")
  print(pars$mu)
  cat("\nCovariance (Sigma):\n")
  print(pars$s_mat)
  sink()
  cat(sprintf("  Summary: %s\n", summary_path))

  cat("\n=== Pipeline complete ===\n")
  invisible(list(
    suitability_png  = png_path,
    suitability_tif  = raster_path,
    ellipsoid_params = pars_path,
    occurrences_csv  = occ_path,
    summary_txt      = summary_path
  ))
}


# ── Main pipeline ────────────────────────────────────────────────────
main <- function() {
  opts <- parse_args()
  cat(sprintf("\n=== Niche Pipeline: %s — M-restricted ===\n\n", opts$species))

  # Step 1: Get occurrences
  occ <- get_occurrences(opts$species, opts$gbif_parquet,
                         opts$use_gbif_api, opts$gbif_limit)

  # Step 2: Filter unique records
  occ <- filter_unique(occ)

  # Step 3: Remove geographic outliers
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

  # Step 6: Environmental IQR filtering (bioclim values)
  occ_env <- filter_env_iqr(occ_env, bioclim_vars, opts$env_iqr_factor)

  # Step 7: Build M mask from ecoregions (BEFORE model fitting — Barve 2011)
  m_mask <- build_m_mask(occ_env, opts$ecoregions, opts$ecoregion_pct)

  # Step 8: Crop bioclim to M
  env_masked <- crop_bioclim_with_mask(env_stack, m_mask)

  # Step 9: Fit nicher ellipsoid
  fit <- fit_nicher_ellipsoid(occ_env, bioclim_vars, opts$num_starts)

  # Step 10: Project on M-cropped rasters + write outputs
  dir.create(opts$output_dir, recursive = TRUE, showWarnings = FALSE)
  paths <- project_and_write(fit, env_masked, occ_env, opts$species, opts$output_dir)
}


# ── Entry point ──────────────────────────────────────────────────────
if (!interactive()) {
  main()
}
