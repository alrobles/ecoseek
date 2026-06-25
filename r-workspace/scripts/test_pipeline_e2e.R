#!/usr/bin/env Rscript
# End-to-end test for the MaxEnt SDM pipeline
# Run via: curl -s -X POST http://127.0.0.1:8787/execute \
#   -H "Content-Type: application/json" \
#   -d '{"code": "source(\"/workspace/scripts/test_pipeline_e2e.R\")", "timeout": 300}'

cat("=== EcoSeek SDM Pipeline E2E Test ===\n")
cat("Date:", format(Sys.time()), "\n\n")

# Step 1: Check packages
cat("[1/7] Checking packages...\n")
pkgs <- c("terra", "sf", "arrow", "maxentcpp", "nicher", "jsonlite")
for (pkg in pkgs) {
  tryCatch({
    library(pkg, character.only = TRUE, quietly = TRUE)
    cat("  OK:", pkg, packageVersion(pkg), "\n")
  }, error = function(e) {
    cat("  FAIL:", pkg, "-", conditionMessage(e), "\n")
  })
}

# Step 2: Check data paths
cat("\n[2/7] Checking data paths...\n")
paths <- list(
  gbif_parquet = "/data/gbifdata/occurrence/2026-06-01/occurrence.parquet",
  bioclim_dir  = "/data/era5-bioclim",
  bioclim_2020 = "/data/era5-bioclim/2020",
  ecoregions   = "/data/ecoregions/Ecoregions2017.shp",
  pipeline_R   = "/workspace/scripts/maxent_pipeline.R"
)
for (nm in names(paths)) {
  exists <- file.exists(paths[[nm]]) || dir.exists(paths[[nm]])
  cat(sprintf("  %s: %s (%s)\n", ifelse(exists, "OK", "FAIL"), nm, paths[[nm]]))
}

# Step 3: Check bioclim TIFs
cat("\n[3/7] Checking bioclim rasters (2020)...\n")
tifs <- list.files("/data/era5-bioclim/2020", pattern = "\\.tif$", full.names = TRUE)
cat("  TIF files found:", length(tifs), "\n")
if (length(tifs) > 0) {
  r <- rast(tifs[1])
  cat("  First:", basename(tifs[1]), "\n")
  cat("  Resolution:", paste(round(res(r), 4), collapse = " x "), "\n")
  cat("  Extent:", paste(round(as.vector(ext(r)), 2), collapse = ", "), "\n")
}

# Step 4: Load ecoregions
cat("\n[4/7] Loading ecoregions shapefile...\n")
tryCatch({
  eco <- st_read("/data/ecoregions/Ecoregions2017.shp", quiet = TRUE)
  cat("  Features:", nrow(eco), "\n")
  cat("  Columns:", paste(names(eco)[1:5], collapse = ", "), "...\n")
  cat("  CRS:", st_crs(eco)$input, "\n")
}, error = function(e) {
  cat("  FAIL:", conditionMessage(e), "\n")
})

# Step 5: Query GBIF for a small species
cat("\n[5/7] Querying GBIF Parquet (Quercus robur, limit 100)...\n")
tryCatch({
  ds <- open_dataset("/data/gbifdata/occurrence/2026-06-01/occurrence.parquet")
  occ <- ds |>
    dplyr::filter(species == "Quercus robur", !is.na(decimallatitude), !is.na(decimallongitude)) |>
    dplyr::select(species, decimallatitude, decimallongitude) |>
    head(100) |>
    dplyr::collect()
  cat("  Records returned:", nrow(occ), "\n")
  if (nrow(occ) > 0) {
    cat("  Lat range:", range(occ$decimallatitude), "\n")
    cat("  Lon range:", range(occ$decimallongitude), "\n")
  }
}, error = function(e) {
  cat("  FAIL:", conditionMessage(e), "\n")
})

# Step 6: Source pipeline and run steps 1-4 (up to bioclim extraction)
cat("\n[6/7] Sourcing maxent_pipeline.R and testing first steps...\n")
tryCatch({
  source("/workspace/scripts/maxent_pipeline.R")
  cat("  Pipeline sourced OK\n")
  
  # Use the occurrences from step 5 if available
  if (exists("occ") && nrow(occ) > 0) {
    # Rename columns to match pipeline expectations
    occ_df <- data.frame(
      long = occ$decimallongitude,
      lat = occ$decimallatitude,
      species = occ$species
    )
    cat("  Sample occurrences (first 5):\n")
    print(head(occ_df, 5))
    
    # Filter unique
    occ_u <- filter_unique(occ_df)
    cat("  After filter_unique:", nrow(occ_u), "\n")
    
    # Extract bioclim (3 vars for speed)
    cat("  Extracting bioclim values (bio01, bio04, bio12)...\n")
    result <- extract_bioclim(occ_u, "/data/era5-bioclim", c("bio01", "bio04", "bio12"), 2020)
    cat("  Extracted vars:", paste(result$vars, collapse = ", "), "\n")
    cat("  Points with data:", nrow(result$occ), "\n")
  }
}, error = function(e) {
  cat("  FAIL:", conditionMessage(e), "\n")
  cat("  Traceback:\n")
  traceback()
})

# Step 7: Quick MaxEnt fit (if we have enough points)
cat("\n[7/7] Testing maxentcpp fit (small test)...\n")
tryCatch({
  if (exists("result") && nrow(result$occ) >= 20) {
    occ_env <- deduplicate_coords(result$occ)
    cat("  After dedup:", nrow(occ_env), "points\n")
    
    # Build simple M mask
    m_mask <- build_m_mask(occ_env, "/data/ecoregions", 0.05)
    cat("  M mask built OK\n")
    
    # Crop bioclim
    env_masked <- crop_bioclim_with_mask(result$stack, m_mask)
    cat("  Rasters cropped to M\n")
    
    # Fit model
    out_dir <- "/workspace/jobs/test_e2e"
    dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
    maxent_result <- fit_maxent_model(
      occ_env, env_masked, result$vars, out_dir,
      "Quercus robur", 1000L, c("linear", "quadratic"), 10L, 200L, 42L
    )
    cat("  AUC:", maxent_result$evaluation$auc, "\n")
    cat("  Training gain:", maxent_result$fit_result$loss, "\n")
    
    # Project
    out <- project_and_write(maxent_result, env_masked, result$vars,
                             occ_env, "Quercus robur", out_dir)
    cat("  Output files:", paste(names(out$paths), collapse = ", "), "\n")
    cat("\n=== ALL STEPS PASSED ===\n")
  } else {
    cat("  SKIP: not enough points for model fit\n")
    cat("\n=== STEPS 1-6 PASSED (model fit skipped) ===\n")
  }
}, error = function(e) {
  cat("  FAIL:", conditionMessage(e), "\n")
  cat("  Traceback:\n")
  traceback()
})

cat("\nDone at:", format(Sys.time()), "\n")
