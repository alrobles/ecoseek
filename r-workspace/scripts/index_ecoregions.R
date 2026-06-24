#!/usr/bin/env Rscript
# index_ecoregions.R — One-time conversion of Ecoregions2017.shp → DuckDB
#
# Creates a persistent DuckDB database with spatial index for fast
# point-in-polygon lookups. Run once; subsequent pipeline runs use
# the indexed DB (~milliseconds vs ~minutes for shapefile I/O).
#
# Usage:
#   Rscript index_ecoregions.R [--shp_dir /path/to/ecoregions] [--db_path /path/to/ecoregions.duckdb]
#
# Defaults:
#   --shp_dir  /media/reumanlab/TOSHIBA_EXT/ecoregions
#   --db_path  /media/reumanlab/TOSHIBA_EXT/ecoregions/ecoregions.duckdb

suppressPackageStartupMessages({
  library(sf)
  library(duckdb)
  library(DBI)
})

args <- commandArgs(trailingOnly = TRUE)
shp_dir <- "/media/reumanlab/TOSHIBA_EXT/ecoregions"
db_path <- NULL

i <- 1L
while (i <= length(args)) {
  if (args[i] == "--shp_dir" && i < length(args)) {
    shp_dir <- args[i + 1L]; i <- i + 2L
  } else if (args[i] == "--db_path" && i < length(args)) {
    db_path <- args[i + 1L]; i <- i + 2L
  } else {
    i <- i + 1L
  }
}

if (is.null(db_path)) db_path <- file.path(shp_dir, "ecoregions.duckdb")

shp_path <- file.path(shp_dir, "Ecoregions2017.shp")
if (!file.exists(shp_path)) {
  shp_candidates <- list.files(shp_dir, pattern = "\\.shp$",
                                full.names = TRUE, recursive = TRUE)
  if (length(shp_candidates) == 0) stop("No .shp files found in ", shp_dir)
  shp_path <- shp_candidates[1]
}

cat(sprintf("=== Indexing Ecoregions → DuckDB ===\n"))
cat(sprintf("  Shapefile: %s\n", shp_path))
cat(sprintf("  Database:  %s\n", db_path))

# Remove existing DB to rebuild
if (file.exists(db_path)) {
  file.remove(db_path)
  wal <- paste0(db_path, ".wal")
  if (file.exists(wal)) file.remove(wal)
}

# Load shapefile with sf (disable S2 for invalid geom tolerance)
cat("  Loading shapefile...\n")
old_s2 <- sf::sf_use_s2()
sf::sf_use_s2(FALSE)
eco <- sf::st_read(shp_path, quiet = TRUE)
eco <- sf::st_make_valid(eco)
if (!identical(sf::st_crs(eco)$epsg, 4326L)) {
  eco <- sf::st_transform(eco, 4326)
}
cat(sprintf("  Loaded %d ecoregion polygons\n", nrow(eco)))

# Keep only essential columns to reduce DB size
keep_cols <- intersect(c("ECO_NAME", "ECO_ID", "BIOME_NUM", "BIOME_NAME",
                          "REALM", "ECO_BIOME_", "NNH", "COLOR", "COLOR_BIO",
                          "COLOR_NNH", "SHAPE_LENG", "SHAPE_AREA"), names(eco))
# Always keep ECO_NAME as primary ID
if (!"ECO_NAME" %in% keep_cols) {
  keep_cols <- c(names(eco)[1], keep_cols)
}
geo_col <- attr(eco, "sf_column")
eco_slim <- eco[, c(keep_cols, geo_col)]

# Convert geometry to WKT for DuckDB ingestion
cat("  Converting geometry to WKT...\n")
eco_df <- sf::st_drop_geometry(eco_slim)
eco_df$geom_wkt <- sf::st_as_text(sf::st_geometry(eco_slim))
sf::sf_use_s2(old_s2)

# Create DuckDB and load spatial extension
cat("  Creating DuckDB database...\n")
con <- dbConnect(duckdb::duckdb(), dbdir = db_path)

dbExecute(con, "INSTALL spatial; LOAD spatial;")

# Write data frame to temp table
dbWriteTable(con, "eco_raw", eco_df, overwrite = TRUE)

# Create final table with proper geometry column
cat("  Creating spatial table with geometry index...\n")
cols_sql <- paste(sprintf('"%s"', keep_cols), collapse = ", ")
dbExecute(con, sprintf(
  "CREATE TABLE ecoregions AS
   SELECT %s, ST_GeomFromText(geom_wkt) AS geom
   FROM eco_raw",
  cols_sql
))
dbExecute(con, "DROP TABLE eco_raw")

# Verify
n <- dbGetQuery(con, "SELECT COUNT(*) AS n FROM ecoregions")$n
cat(sprintf("  Indexed %d ecoregions in DuckDB\n", n))

# Test a spatial query
test <- dbGetQuery(con, "
  SELECT ECO_NAME
  FROM ecoregions
  WHERE ST_Contains(geom, ST_Point(0.0, 51.5))
  LIMIT 1
")
if (nrow(test) > 0) {
  cat(sprintf("  Test query (lon=0, lat=51.5): %s ✓\n", test$ECO_NAME[1]))
} else {
  cat("  Test query returned no results (point may be in ocean)\n")
}

dbDisconnect(con, shutdown = TRUE)

db_size <- file.info(db_path)$size / 1024 / 1024
cat(sprintf("\n=== Done! Database: %s (%.1f MB) ===\n", db_path, db_size))
cat("Pipeline will auto-detect this DB and skip shapefile loading.\n")
