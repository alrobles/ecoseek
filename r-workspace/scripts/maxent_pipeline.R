# maxent_pipeline.R — MaxEnt Species Distribution Modeling via maxentcpp
#
# Implements the 10-step MaxEnt SDM algorithm (Barve et al. 2011 compliant):
#   1. Download/read GBIF occurrence points
#   2. Filter unique records
#   3. Remove geographic outliers (IQR on lon/lat)
#   4. Extract ERA5-bioclim at presence points (all 19 vars per cell)
#   5. Deduplicate coordinates
#   6. Environmental IQR filtering (remove bioclim outliers)
#   7. Build M mask: intersect points with ecoregions, dissolve to M polygon
#   8. Crop ERA5-bioclim with M mask
#   9. Fit MaxEnt model via maxentcpp::maxent_run() with background WITHIN M
#  10. Project MaxEnt model (cloglog) on M-cropped raster + write outputs
#
# Key scientific references:
#   - Barve et al. 2011. Ecological Modelling 222: 1810-1819 (M mask)
#   - Soberon & Peterson 2005. Biodiversity Informatics 2: 1-10 (BAM)
#   - Phillips et al. 2006. Ecological Modelling 190: 231-259 (MaxEnt)
#
# Usage:
#   Rscript maxent_pipeline.R --species "Panthera onca" [options]
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
  library(maxentcpp)
  library(duckdb)
  library(DBI)
})

# ── CLI argument parsing ──────────────────────────────────────────────
parse_args <- function() {
  args <- commandArgs(trailingOnly = TRUE)
  opts <- list(
    species       = NULL,
    bioclim_dir   = "/media/reumanlab/TOSHIBA_EXT/era5-bioclim",
    ecoregions    = "/media/reumanlab/TOSHIBA_EXT/ecoregions",
    gbif_parquet  = "/media/reumanlab/TOSHIBA_EXT/gbifdata/occurrence/2026-06-01/occurrence.parquet",
    output_dir    = "./output",
    bioclim_vars  = paste0("bio", sprintf("%02d", 1:19)),
    bioclim_year  = 2020L,
    n_background  = 10000L,
    feature_types = "linear,quadratic,hinge",
    n_hinges      = 15L,
    max_iter      = 500L,
    iqr_factor    = 1.5,
    env_iqr_factor = 1.5,
    ecoregion_pct = 0.05,
    use_gbif_api  = FALSE,
    gbif_limit    = 50000L,
    seed          = 42L
  )

  i <- 1L
  while (i <= length(args)) {
    key <- sub("^--", "", args[i])
    if (key == "chelsa_dir") key <- "bioclim_dir"
    if (key %in% names(opts)) {
      i <- i + 1L
      opts[[key]] <- args[i]
    } else if (key == "help") {
      cat("Usage: Rscript maxent_pipeline.R --species \"Genus species\" [options]\n")
      cat("\nOptions:\n")
      cat("  --species         Species name (required)\n")
      cat("  --bioclim_dir     Path to ERA5-bioclim directory\n")
      cat("  --bioclim_year    Year for bioclim data (default: 2020)\n")
      cat("  --ecoregions      Path to ecoregions shapefiles\n")
      cat("  --gbif_parquet    Path to GBIF occurrence parquet\n")
      cat("  --output_dir      Output directory\n")
      cat("  --n_background    Number of background points (default: 10000)\n")
      cat("  --feature_types   Comma-separated feature types (default: linear,quadratic,hinge)\n")
      cat("  --n_hinges        Number of hinge knots (default: 15)\n")
      cat("  --max_iter        Max training iterations (default: 500)\n")
      cat("  --iqr_factor      IQR multiplier for geographic outlier removal (default: 1.5)\n")
      cat("  --env_iqr_factor  IQR multiplier for environmental outlier removal (default: 1.5)\n")
      cat("  --ecoregion_pct   Min fraction of points to keep ecoregion (default: 0.05)\n")
      cat("  --use_gbif_api    If TRUE, query GBIF API instead of parquet\n")
      cat("  --gbif_limit      Max records from GBIF API (default: 50000)\n")
      cat("  --seed            Random seed (default: 42)\n")
      quit(status = 0)
    }
    i <- i + 1L
  }

  opts$n_background   <- as.integer(opts$n_background)
  opts$n_hinges       <- as.integer(opts$n_hinges)
  opts$max_iter       <- as.integer(opts$max_iter)
  opts$bioclim_year   <- as.integer(opts$bioclim_year)
  opts$iqr_factor     <- as.numeric(opts$iqr_factor)
  opts$env_iqr_factor <- as.numeric(opts$env_iqr_factor)
  opts$ecoregion_pct  <- as.numeric(opts$ecoregion_pct)
  opts$gbif_limit     <- as.integer(opts$gbif_limit)
  opts$use_gbif_api   <- as.logical(opts$use_gbif_api)
  opts$seed           <- as.integer(opts$seed)

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
      dplyr::collect()
    occ <- as.data.frame(occ)
    occ <- occ[!is.na(occ$decimalLongitude) & !is.na(occ$decimalLatitude), ]
  }

  cat(sprintf("  Found %d occurrence records\n", nrow(occ)))
  if (nrow(occ) < 5) {
    stop(sprintf("Too few occurrences for %s: %d (need >= 5)", species, nrow(occ)))
  }
  occ
}


# ── Step 2: Filter unique records ─────────────────────────────────────
filter_unique <- function(occ) {
  cat("[2/10] Filtering unique records...\n")
  n_before <- nrow(occ)
  occ <- unique(occ[, c("decimalLongitude", "decimalLatitude")])
  names(occ) <- c("long", "lat")
  cat(sprintf("  %d → %d unique lon/lat pairs\n", n_before, nrow(occ)))
  occ
}


# ── Step 3: Remove geographic outliers (IQR on coordinates) ───────────
remove_outliers_iqr <- function(occ, iqr_factor = 1.5) {
  cat(sprintf("[3/10] Removing geographic outliers (IQR × %.1f)...\n", iqr_factor))
  n_before <- nrow(occ)
  for (col in c("long", "lat")) {
    q <- quantile(occ[[col]], c(0.25, 0.75), na.rm = TRUE)
    iqr <- q[2] - q[1]
    occ <- occ[occ[[col]] >= q[1] - iqr_factor * iqr &
               occ[[col]] <= q[2] + iqr_factor * iqr, ]
  }
  cat(sprintf("  %d → %d after geographic outlier removal\n", n_before, nrow(occ)))
  if (nrow(occ) < 5) stop("Too few points after outlier removal")
  occ
}


# ── Step 4: Extract ERA5-bioclim at presence points ───────────────────
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
    tif_files <- tif_files[exists_mask]
    bioclim_vars <- bioclim_vars[exists_mask]
  }

  env_stack <- terra::rast(tif_files)
  names(env_stack) <- bioclim_vars
  pts <- terra::vect(occ, geom = c("long", "lat"), crs = "EPSG:4326")
  vals <- terra::extract(env_stack, pts, ID = FALSE)
  complete <- complete.cases(vals)

  cat(sprintf("  Extracted %d vars for %d points (%d complete)\n",
              ncol(vals), nrow(vals), sum(complete)))

  occ_env <- cbind(occ[complete, ], vals[complete, ])
  list(occ = occ_env, stack = env_stack, vars = bioclim_vars)
}


# ── Step 5: Deduplicate coordinates ───────────────────────────────────
deduplicate_coords <- function(occ_env) {
  cat("[5/10] Deduplicating coordinates...\n")
  n_before <- nrow(occ_env)
  occ_env <- occ_env[!duplicated(occ_env[, c("long", "lat")]), ]
  cat(sprintf("  %d → %d after dedup\n", n_before, nrow(occ_env)))
  if (nrow(occ_env) < 5) stop("Too few unique coords after dedup")
  occ_env
}


# ── Step 6: Environmental IQR filtering ──────────────────────────────
# Removes presence points with bioclim values outside the IQR range
# for ANY variable. This eliminates environmental noise per standard
# SDM best practice (outliers in env space often indicate georeferencing
# errors or vagrant individuals).
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
  cat(sprintf("  %d → %d after environmental IQR filtering (%d removed)\n",
              n_before, nrow(occ_env), n_before - nrow(occ_env)))
  if (nrow(occ_env) < 5) stop("Too few points after environmental IQR filtering")
  occ_env
}


# ── Step 7: Build M mask from ecoregions (Barve et al. 2011) ─────────
# Uses DuckDB spatial index when available (milliseconds).
# Falls back to shapefile with bbox filter (slower).
build_m_mask <- function(occ, ecoregions_dir, ecoregion_pct = 0.05) {
  cat("[7/10] Building M mask from ecoregions...\n")

  old_s2 <- sf::sf_use_s2()
  sf::sf_use_s2(FALSE)
  on.exit(sf::sf_use_s2(old_s2))

  db_path <- file.path(ecoregions_dir, "ecoregions.duckdb")
  use_duckdb <- file.exists(db_path) && requireNamespace("duckdb", quietly = TRUE)

  if (use_duckdb) {
    cat(sprintf("  Using DuckDB spatial index: %s\n", basename(db_path)))
    result <- build_m_mask_duckdb(occ, db_path, ecoregion_pct)
  } else {
    cat("  DuckDB not available, falling back to shapefile...\n")
    result <- build_m_mask_shapefile(occ, ecoregions_dir, ecoregion_pct)
  }
  result
}

build_m_mask_duckdb <- function(occ, db_path, ecoregion_pct = 0.05) {
  con <- DBI::dbConnect(duckdb::duckdb(), dbdir = db_path, read_only = TRUE)
  on.exit(DBI::dbDisconnect(con, shutdown = TRUE))
  DBI::dbExecute(con, "LOAD spatial;")

  # Build point list for SQL IN clause
  pts_sql <- paste(
    sprintf("(%f, %f)", occ$long, occ$lat),
    collapse = ", "
  )

  # Spatial join via DuckDB: find ecoregion for each point
  query <- sprintf("
    WITH pts AS (
      SELECT column0 AS lon, column1 AS lat
      FROM (VALUES %s)
    )
    SELECT p.lon, p.lat, e.ECO_NAME
    FROM pts p, ecoregions e
    WHERE ST_Contains(e.geom, ST_Point(p.lon, p.lat))
  ", pts_sql)

  t0 <- proc.time()[3]
  join_result <- DBI::dbGetQuery(con, query)
  dt <- proc.time()[3] - t0
  cat(sprintf("  DuckDB spatial join: %d matches in %.1fs\n",
              nrow(join_result), dt))

  if (nrow(join_result) == 0) {
    cat("  Warning: no points matched ecoregions, using convex hull\n")
    pts_sf <- sf::st_as_sf(occ, coords = c("long", "lat"), crs = 4326)
    hull <- sf::st_buffer(sf::st_convex_hull(sf::st_union(pts_sf)), dist = 2)
    return(terra::vect(hull))
  }

  # Select ecoregions with enough points
  freq <- table(join_result$ECO_NAME)
  n_total <- nrow(occ)
  keep <- names(freq[freq >= max(1, ceiling(n_total * ecoregion_pct))])
  if (length(keep) == 0) keep <- names(freq[freq > 0])
  cat(sprintf("  %d ecoregions selected (of %d with points)\n",
              length(keep), length(freq)))

  # Retrieve geometries for selected ecoregions from DuckDB
  eco_names_sql <- paste(sprintf("'%s'", gsub("'", "''", keep)), collapse = ", ")
  eco_wkt <- DBI::dbGetQuery(con, sprintf("
    SELECT ECO_NAME, ST_AsText(geom) AS wkt
    FROM ecoregions
    WHERE ECO_NAME IN (%s)
  ", eco_names_sql))

  # Convert WKT geometries to sf → union → vect
  geoms <- sf::st_as_sfc(eco_wkt$wkt, crs = 4326)
  m_poly <- sf::st_union(sf::st_make_valid(geoms))
  cat(sprintf("  M mask built from %d ecoregion(s)\n", length(keep)))
  terra::vect(m_poly)
}

build_m_mask_shapefile <- function(occ, ecoregions_dir, ecoregion_pct = 0.05) {
  shp_path <- file.path(ecoregions_dir, "Ecoregions2017.shp")
  if (!file.exists(shp_path)) {
    shp_candidates <- list.files(ecoregions_dir, pattern = "\\.shp$",
                                  full.names = TRUE, recursive = TRUE)
    if (length(shp_candidates) == 0) {
      cat("  Warning: no ecoregion shapefiles found, using convex hull as M\n")
      pts <- sf::st_as_sf(occ, coords = c("long", "lat"), crs = 4326)
      hull <- sf::st_convex_hull(sf::st_union(pts))
      hull_buf <- sf::st_buffer(hull, dist = 2)
      return(terra::vect(hull_buf))
    }
    shp_path <- shp_candidates[1]
  }

  pts_sf <- sf::st_as_sf(occ, coords = c("long", "lat"), crs = 4326)
  bbox <- sf::st_bbox(pts_sf)
  bbox_buf <- sf::st_bbox(c(
    xmin = max(bbox["xmin"] - 5, -180),
    ymin = max(bbox["ymin"] - 5, -90),
    xmax = min(bbox["xmax"] + 5, 180),
    ymax = min(bbox["ymax"] + 5, 90)
  ), crs = sf::st_crs(4326))
  wkt_filter <- sf::st_as_text(sf::st_as_sfc(bbox_buf))

  eco <- sf::st_read(shp_path, wkt_filter = wkt_filter, quiet = TRUE)
  if (nrow(eco) == 0) eco <- sf::st_read(shp_path, quiet = TRUE)
  eco <- sf::st_make_valid(eco)
  if (!identical(sf::st_crs(eco)$epsg, 4326L)) eco <- sf::st_transform(eco, 4326)

  join <- sf::st_join(pts_sf, eco, join = sf::st_intersects)
  eco_col <- intersect(c("ECO_NAME", "ECO_ID"), names(join))
  eco_col <- if (length(eco_col) > 0) eco_col[1] else {
    chr_cols <- names(join)[vapply(sf::st_drop_geometry(join), is.character, logical(1))]
    if (length(chr_cols) > 0) chr_cols[1] else names(join)[3]
  }
  join <- join[!is.na(join[[eco_col]]), ]
  freq <- table(join[[eco_col]])
  keep <- names(freq[freq >= max(1, ceiling(nrow(occ) * ecoregion_pct))])
  if (length(keep) == 0) keep <- names(freq[freq > 0])

  m_eco <- eco[eco[[eco_col]] %in% keep, ]
  m_poly <- sf::st_make_valid(sf::st_union(m_eco))
  terra::vect(m_poly)
}


# ── Step 8: Crop bioclim rasters with M mask ──────────────────────────
crop_bioclim_with_mask <- function(env_stack, m_mask) {
  cat("[8/10] Cropping ERA5-bioclim with M mask...\n")
  env_crop <- terra::crop(env_stack, m_mask)
  env_mask <- terra::mask(env_crop, m_mask)
  n_valid <- sum(!is.na(terra::values(env_mask[[1]])))
  cat(sprintf("  Cropped extent: %s\n",
              paste(round(as.vector(terra::ext(env_mask)), 2), collapse = ", ")))
  cat(sprintf("  Valid cells in M: %d\n", n_valid))
  env_mask
}


# ── Step 9: Fit MaxEnt model with background WITHIN M ─────────────────
# Per Barve et al. 2011: background points must be sampled from M,
# not the global extent. This is critical for correct MaxEnt inference.
fit_maxent_model <- function(occ_env, env_masked, bioclim_vars, output_dir,
                             species, n_background = 10000L,
                             feature_types = c("linear", "quadratic", "hinge"),
                             n_hinges = 15L, max_iter = 500L, seed = 42L) {
  cat("[9/10] Fitting MaxEnt model (background within M)...\n")

  env_grids <- lapply(bioclim_vars, function(v) {
    maxent_grid_from_terra(env_masked[[v]], name = v)
  })
  names(env_grids) <- bioclim_vars

  occ_df <- data.frame(
    long = occ_env$long,
    lat  = occ_env$lat
  )

  result <- maxent_run(
    species      = species,
    env_grids    = env_grids,
    occ_df       = occ_df,
    output_dir   = output_dir,
    lon_col      = "long",
    lat_col      = "lat",
    n_background = n_background,
    types        = feature_types,
    n_hinges     = n_hinges,
    max_iter     = max_iter,
    seed         = seed
  )

  cat(sprintf("  AUC: %.4f\n", result$evaluation$auc))
  cat(sprintf("  Training gain: %.4f\n", result$fit_result$loss))
  cat(sprintf("  Presence points: %d\n", nrow(occ_df)))
  cat(sprintf("  Background points: %d (sampled within M)\n", n_background))
  result
}


# ── Step 10: Project + write outputs ──────────────────────────────────
project_and_write <- function(maxent_result, env_masked, bioclim_vars,
                              occ_env, species, output_dir) {
  cat("[10/10] Projecting model and writing outputs...\n")
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
  sp_clean <- gsub("[^a-zA-Z0-9]", "_", species)

  # Project MaxEnt model (cloglog) on M-cropped rasters
  env_grids <- lapply(bioclim_vars, function(v) {
    maxent_grid_from_terra(env_masked[[v]], name = v)
  })
  names(env_grids) <- bioclim_vars

  pred_grid <- maxent_project_cloglog(
    maxent_result$model,
    unname(env_grids),
    bioclim_vars
  )
  pred_raster <- maxent_grid_to_terra(pred_grid, crs = terra::crs(env_masked))

  paths <- list()

  # Suitability GeoTIFF
  tif_path <- file.path(output_dir, paste0(sp_clean, "_suitability.tif"))
  terra::writeRaster(pred_raster, tif_path, overwrite = TRUE)
  paths$suitability_tif <- tif_path

  # Suitability PNG
  png_path <- file.path(output_dir, paste0(sp_clean, "_suitability.png"))
  grDevices::png(png_path, width = 1000, height = 700, res = 120)
  suit_cols <- grDevices::colorRampPalette(
    c("#2166AC", "#67A9CF", "#D1E5F0", "#FDDBC7", "#EF8A62", "#B2182B")
  )(100)
  terra::plot(pred_raster, col = suit_cols, range = c(0, 1),
              main = paste0(species, "\nMaxEnt suitability (M-restricted)"),
              plg = list(title = "Suitability", title.cex = 0.8),
              mar = c(3, 3, 3, 5))
  if (nrow(occ_env) > 0) {
    graphics::points(occ_env$long, occ_env$lat,
                     pch = 16, cex = 0.4,
                     col = grDevices::adjustcolor("black", 0.5))
  }
  grDevices::dev.off()
  paths$suitability_png <- png_path

  # Summary CSV
  summary_path <- file.path(output_dir, paste0(sp_clean, "_summary.csv"))
  summary_df <- data.frame(
    species       = species,
    n_presence    = nrow(occ_env),
    auc           = maxent_result$evaluation$auc,
    training_gain = maxent_result$fit_result$loss,
    algorithm     = "maxentcpp",
    m_mask        = "ecoregion",
    stringsAsFactors = FALSE
  )
  write.csv(summary_df, summary_path, row.names = FALSE)
  paths$summary_csv <- summary_path

  # Variable importance
  if (!is.null(maxent_result$contributions)) {
    contrib_path <- file.path(output_dir, paste0(sp_clean, "_contributions.csv"))
    write.csv(maxent_result$contributions, contrib_path, row.names = FALSE)
    paths$contributions_csv <- contrib_path
  }
  if (!is.null(maxent_result$permutation_importance)) {
    perm_path <- file.path(output_dir, paste0(sp_clean, "_permutation_importance.csv"))
    write.csv(maxent_result$permutation_importance, perm_path, row.names = FALSE)
    paths$permutation_importance_csv <- perm_path
  }

  # Filtered occurrences
  occ_path <- file.path(output_dir, paste0(sp_clean, "_occurrences.csv"))
  write.csv(occ_env, occ_path, row.names = FALSE)
  paths$occurrences_csv <- occ_path

  cat(sprintf("  Suitability raster: %s\n", tif_path))
  cat(sprintf("  PNG map: %s\n", png_path))
  cat(sprintf("  Files: %s\n", paste(basename(unlist(paths)), collapse = ", ")))
  list(pred_raster = pred_raster, paths = paths)
}


# ── Main ──────────────────────────────────────────────────────────────
main <- function() {
  opts <- parse_args()

  cat(sprintf("\n=== MaxEnt SDM Pipeline (maxentcpp) — M-restricted ===\n"))
  cat(sprintf("Species:     %s\n", opts$species))
  cat(sprintf("Bioclim dir: %s\n", opts$bioclim_dir))
  cat(sprintf("Bioclim year: %d\n", opts$bioclim_year))
  cat(sprintf("Ecoregions:  %s\n", opts$ecoregions))
  cat(sprintf("GBIF source: %s\n",
              if (opts$use_gbif_api) "API" else opts$gbif_parquet))
  cat(sprintf("Output dir:  %s\n\n", opts$output_dir))

  # Step 1: Get occurrences
  occ <- get_occurrences(opts$species, opts$gbif_parquet,
                         opts$use_gbif_api, opts$gbif_limit)

  # Step 2: Filter unique
  occ <- filter_unique(occ)

  # Step 3: Remove geographic outliers
  occ <- remove_outliers_iqr(occ, opts$iqr_factor)

  # Step 4: Extract bioclim
  bioclim_vars <- strsplit(opts$bioclim_vars, ",")[[1]]
  if (length(bioclim_vars) == 1 && grepl(" ", bioclim_vars)) {
    bioclim_vars <- strsplit(bioclim_vars, "\\s+")[[1]]
  }
  result <- extract_bioclim(occ, opts$bioclim_dir, bioclim_vars, opts$bioclim_year)

  # Step 5: Deduplicate
  occ_env <- deduplicate_coords(result$occ)

  # Step 6: Environmental IQR filtering (bioclim values)
  occ_env <- filter_env_iqr(occ_env, result$vars, opts$env_iqr_factor)

  # Step 7: Build M mask from ecoregions (BEFORE model fitting — Barve 2011)
  m_mask <- build_m_mask(occ_env, opts$ecoregions, opts$ecoregion_pct)

  # Step 8: Crop bioclim to M
  env_masked <- crop_bioclim_with_mask(result$stack, m_mask)

  # Step 9: Fit MaxEnt with background WITHIN M
  dir.create(opts$output_dir, recursive = TRUE, showWarnings = FALSE)
  feature_types <- strsplit(opts$feature_types, ",")[[1]]
  maxent_result <- fit_maxent_model(
    occ_env, env_masked, result$vars, opts$output_dir,
    opts$species, opts$n_background, feature_types,
    opts$n_hinges, opts$max_iter, opts$seed
  )

  # Step 10: Project on M-cropped rasters + write outputs
  out <- project_and_write(maxent_result, env_masked, result$vars,
                           occ_env, opts$species, opts$output_dir)

  cat("\n=== Pipeline complete ===\n")
  cat(sprintf("AUC: %.4f\n", maxent_result$evaluation$auc))
  cat(sprintf("M mask: ecoregion-based (Barve et al. 2011)\n"))
  cat(sprintf("Files: %s\n", paste(basename(unlist(out$paths)), collapse = ", ")))
}

if (!interactive()) {
  main()
}
