"""R code executor — agentic bridge to rocker/geospatial workspace.

Emily generates R code via DiDAL or direct response, sends it to the
R workspace container for execution, and reads back the results
(stdout, stderr, plots, CSVs, etc.).

The R workspace runs rocker/geospatial with sf, terra, dismo, vegan,
ape, rgbif, and other ecology packages pre-installed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid

logger = logging.getLogger(__name__)

_R_WORKSPACE_URL = os.environ.get("R_WORKSPACE_URL", "http://r-workspace:8787").rstrip(
    "/"
)

_R_EXEC_TIMEOUT = int(os.environ.get("R_EXEC_TIMEOUT", "300"))


def _is_r_workspace_available() -> bool:
    """Check if the R workspace container is reachable."""
    try:
        from .http_client import http_get_json

        result = http_get_json(f"{_R_WORKSPACE_URL}/health", timeout=5)
        return result.get("status") == "ok"
    except Exception:
        return False


def execute_r_code(
    code: str,
    timeout: int | None = None,
    job_id: str | None = None,
    task_id: str | None = None,
) -> str:
    """Execute R code in the geospatial workspace and return results.

    The R workspace has rocker/geospatial pre-installed with:
    sf, terra, raster, dismo, vegan, ape, picante, rgbif, taxize,
    ENMeval, spocc, CoordinateCleaner, biomod2, and more.

    Args:
        code: R code to execute.
        timeout: Max execution time in seconds (default: 300).
        job_id: Optional job identifier for tracking.

    Returns:
        JSON string with stdout, stderr, output files, and exit code.
    """
    from .http_client import http_post_json

    if not code.strip():
        return json.dumps({"success": False, "error": "empty_code"})

    effective_timeout = min(timeout or _R_EXEC_TIMEOUT, _R_EXEC_TIMEOUT)
    effective_job_id = job_id or str(uuid.uuid4())[:12]

    try:
        result = http_post_json(
            f"{_R_WORKSPACE_URL}/execute",
            payload={
                "code": code,
                "timeout": effective_timeout,
                "job_id": effective_job_id,
            },
            timeout=effective_timeout + 30,
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.error("R execution failed: %s", exc)
        return json.dumps(
            {
                "success": False,
                "error": str(exc)[:500],
                "job_id": effective_job_id,
                "r_workspace_url": _R_WORKSPACE_URL,
            },
            ensure_ascii=False,
        )


def list_r_packages(task_id: str | None = None) -> str:
    """List installed R packages in the geospatial workspace."""
    from .http_client import http_get_json

    try:
        result = http_get_json(f"{_R_WORKSPACE_URL}/packages", timeout=30)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)[:300]})


def r_workspace_status(task_id: str | None = None) -> str:
    """Check R workspace container status and available packages."""
    available = _is_r_workspace_available()
    return json.dumps(
        {
            "available": available,
            "url": _R_WORKSPACE_URL,
            "description": (
                "R geospatial workspace with rocker/geospatial. "
                "Packages: sf, terra, raster, dismo, vegan, ape, rgbif, "
                "taxize, ENMeval, spocc, CoordinateCleaner, biomod2, etc."
            )
            if available
            else "R workspace container is not running.",
        }
    )


# ---------------------------------------------------------------------------
# Post-processing: convert R results to shareable markdown
# ---------------------------------------------------------------------------

_RESULT_JSON_RE = re.compile(r"\[RESULT_JSON\]\s*(\{.*?\})\s*$", re.DOTALL | re.MULTILINE)

_FILE_LABELS = {
    "suitability_png": ("Suitability Map", "image"),
    "suitability_tif": ("Suitability Raster (GeoTIFF)", "download"),
    "summary_csv": ("Model Summary", "download"),
    "summary_txt": ("Model Summary", "download"),
    "contributions_csv": ("Variable Contributions", "download"),
    "permutation_importance_csv": ("Permutation Importance", "download"),
    "occurrences_csv": ("Filtered Occurrences", "download"),
    "ellipsoid_params": ("Ellipsoid Parameters (RDS)", "download"),
}


def _parse_result_json(raw_result: str) -> dict | None:
    """Extract the [RESULT_JSON] object from R workspace stdout."""
    try:
        outer = json.loads(raw_result)
        stdout = outer.get("stdout", "")
    except (json.JSONDecodeError, AttributeError):
        return None

    m = _RESULT_JSON_RE.search(stdout)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _file_url(path: str) -> str:
    """Convert a container-local path to a relative URL served by nginx."""
    if path.startswith("/workspace/"):
        return path
    return path


def _build_markdown(result: dict, algorithm: str) -> str:
    """Build a markdown summary from parsed model results."""
    species = result.get("species", "Unknown")
    lines: list[str] = []

    lines.append(f"## {species} — {algorithm} Results\n")

    # Summary table
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Species | *{species}* |")
    lines.append(f"| Algorithm | {algorithm} |")
    n_pts = result.get("n_points", "—")
    lines.append(f"| Presence points | {n_pts} |")

    if "auc" in result:
        lines.append(f"| AUC | {result['auc']:.4f} |")
    if "training_gain" in result:
        lines.append(f"| Training gain | {result['training_gain']:.4f} |")
    if "neg_loglik" in result:
        lines.append(f"| Neg. log-likelihood | {result['neg_loglik']:.4f} |")
    if "n_background" in result:
        lines.append(f"| Background points | {result['n_background']} |")

    variables = result.get("variables", [])
    if variables:
        lines.append(f"| Variables ({len(variables)}) | {', '.join(variables)} |")
    lines.append("")

    # Embedded suitability map (PNG)
    files = result.get("files", {})
    png_path = files.get("suitability_png", "")
    if png_path:
        url = _file_url(png_path)
        lines.append(f"![{species} suitability map]({url})\n")

    # Download links
    download_links: list[str] = []
    for key, (label, ftype) in _FILE_LABELS.items():
        fpath = files.get(key, "")
        if fpath and ftype == "download":
            url = _file_url(fpath)
            fname = os.path.basename(fpath)
            download_links.append(f"- [{label} ({fname})]({url})")

    if download_links:
        lines.append("### Downloads\n")
        lines.extend(download_links)
        lines.append("")

    return "\n".join(lines)


def _postprocess_model_result(raw_result: str, algorithm: str) -> str:
    """Enrich the raw R execution result with a markdown summary and file URLs."""
    parsed = _parse_result_json(raw_result)
    if not parsed or not parsed.get("success"):
        return raw_result

    markdown = _build_markdown(parsed, algorithm)

    try:
        outer = json.loads(raw_result)
    except json.JSONDecodeError:
        return raw_result

    outer["model_result"] = parsed
    outer["markdown_summary"] = markdown

    file_urls = {}
    for key, path in parsed.get("files", {}).items():
        if path:
            file_urls[key] = _file_url(path)
    outer["file_urls"] = file_urls

    return json.dumps(outer, ensure_ascii=False)


def run_niche_model(
    species: str,
    num_starts: int = 20,
    iqr_factor: float = 1.5,
    ecoregion_pct: float = 0.05,
    bioclim_vars: str = "bio01,bio02,bio03,bio04,bio05,bio06,bio07,bio08,bio09,bio10,bio11,bio12,bio13,bio14,bio15,bio16,bio17,bio18,bio19",
    bioclim_year: int = 2020,
    use_gbif_api: bool = False,
    task_id: str | None = None,
) -> str:
    """Run the niche modeling pipeline for a species.

    Executes the 10-step ellipsoidal niche modeling algorithm:
    1. Get GBIF occurrences (from parquet or API)
    2. Filter unique records
    3. Remove outliers (IQR)
    4. Extract ERA5-bioclim variables (flexible subset)
    5. Deduplicate coordinates
    6. Fit nicher ellipsoid (presence_only)
    7. Build M mask from ecoregions (>5% points threshold)
    8. Crop bioclim rasters with M mask
    9. Project nicher ellipse onto cropped raster
    10. Write suitability GeoTIFF + PNG map + summary

    Args:
        species: Scientific name (e.g., "Panthera onca").
        num_starts: Multi-start optimization restarts (default: 20).
        iqr_factor: IQR multiplier for outlier removal (default: 1.5).
        ecoregion_pct: Min fraction of points to keep an ecoregion (default: 0.05).
        bioclim_vars: Comma-separated ERA5-bioclim variable names.
            Pass any subset (e.g. "bio01,bio04,bio12"). Default: all 19.
        bioclim_year: Year for bioclim data (default: 2020).
        use_gbif_api: If True, query GBIF API instead of local parquet.

    Returns:
        JSON with markdown summary, file URLs, embedded suitability map.
    """
    vars_r = ", ".join(f'"{v.strip()}"' for v in bioclim_vars.split(","))

    code = f'''
suppressPackageStartupMessages({{
  library(terra)
  library(sf)
  library(nicher)
  {"library(arrow)" if not use_gbif_api else "library(rgbif)"}
}})

source("/workspace/scripts/niche_pipeline.R")

# Override parse_args for programmatic invocation
opts <- list(
  species       = "{species}",
  bioclim_dir   = Sys.getenv("BIOCLIM_DIR", "/media/reumanlab/TOSHIBA_EXT/era5-bioclim"),
  ecoregions    = Sys.getenv("ECOREGIONS_DIR", "/home/a474r867/work/ecoregions"),
  gbif_parquet  = Sys.getenv("GBIF_PARQUET", "/media/reumanlab/TOSHIBA_EXT/gbifdata/occurrence/2026-06-01/occurrence.parquet"),
  output_dir    = "/workspace/jobs/niche_{species.replace(" ", "_")}",
  bioclim_vars  = c({vars_r}),
  bioclim_year  = {bioclim_year}L,
  num_starts    = {num_starts}L,
  iqr_factor    = {iqr_factor},
  ecoregion_pct = {ecoregion_pct},
  use_gbif_api  = {"TRUE" if use_gbif_api else "FALSE"},
  gbif_limit    = 50000L
)

tryCatch({{
  occ <- get_occurrences(opts$species, opts$gbif_parquet,
                         opts$use_gbif_api, opts$gbif_limit)
  occ <- filter_unique(occ)
  occ <- remove_outliers_iqr(occ, opts$iqr_factor)
  result <- extract_bioclim(occ, opts$bioclim_dir, opts$bioclim_vars, opts$bioclim_year)
  occ_env <- deduplicate_coords(result$occ)
  fit <- fit_nicher_ellipsoid(occ_env, result$vars, opts$num_starts)
  m_mask <- build_m_mask(occ, opts$ecoregions, opts$ecoregion_pct)
  env_masked <- crop_bioclim_with_mask(result$stack, m_mask)
  sp_clean <- gsub("[^a-zA-Z0-9]", "_", opts$species)
  out_path <- file.path(opts$output_dir, paste0(sp_clean, "_suitability.tif"))
  dir.create(opts$output_dir, recursive = TRUE, showWarnings = FALSE)
  suit <- project_nicher(fit, env_masked, out_path)
  paths <- write_outputs(suit, fit, occ_env, opts$species, opts$output_dir)
  cat("\\n[RESULT_JSON]", jsonlite::toJSON(list(
    success = TRUE,
    species = opts$species,
    n_points = nrow(occ_env),
    variables = result$vars,
    neg_loglik = fit$best$value,
    output_dir = opts$output_dir,
    files = paths
  ), auto_unbox = TRUE), "\\n")
}}, error = function(e) {{
  cat("\\n[RESULT_JSON]", jsonlite::toJSON(list(
    success = FALSE,
    species = opts$species,
    error = conditionMessage(e)
  ), auto_unbox = TRUE), "\\n")
}})
'''

    raw = execute_r_code(code=code, timeout=_R_EXEC_TIMEOUT, task_id=task_id)
    return _postprocess_model_result(raw, "nicher (ellipsoidal)")


def run_maxent_model(
    species: str,
    n_background: int = 10000,
    feature_types: str = "linear,quadratic,hinge",
    n_hinges: int = 15,
    max_iter: int = 500,
    iqr_factor: float = 1.5,
    ecoregion_pct: float = 0.05,
    bioclim_vars: str = "bio01,bio02,bio03,bio04,bio05,bio06,bio07,bio08,bio09,bio10,bio11,bio12,bio13,bio14,bio15,bio16,bio17,bio18,bio19",
    bioclim_year: int = 2020,
    use_gbif_api: bool = False,
    seed: int = 42,
    task_id: str | None = None,
) -> str:
    """Run the MaxEnt SDM pipeline for a species via maxentcpp.

    Executes the 10-step MaxEnt algorithm:
    1. Get GBIF occurrences (from parquet or API)
    2. Filter unique records
    3. Remove outliers (IQR)
    4. Extract ERA5-bioclim variables (flexible subset)
    5. Deduplicate coordinates
    6. Fit MaxEnt via maxentcpp::maxent_run()
    7. Build M mask from ecoregions (>5% points threshold)
    8. Crop bioclim rasters with M mask
    9. Project MaxEnt model (cloglog) onto cropped raster
    10. Write suitability PNG + GeoTIFF + diagnostics

    Args:
        species: Scientific name (e.g., "Panthera onca").
        n_background: Number of background points (default: 10000).
        feature_types: Comma-separated feature types (default: linear,quadratic,hinge).
        n_hinges: Number of hinge knots (default: 15).
        max_iter: Maximum training iterations (default: 500).
        iqr_factor: IQR multiplier for outlier removal (default: 1.5).
        ecoregion_pct: Min fraction of points to keep an ecoregion (default: 0.05).
        bioclim_vars: Comma-separated ERA5-bioclim variable names.
            Pass any subset (e.g. "bio01,bio04,bio12"). Default: all 19.
        bioclim_year: Year for bioclim data (default: 2020).
        use_gbif_api: If True, query GBIF API instead of local parquet.
        seed: Random seed for background sampling (default: 42).

    Returns:
        JSON with markdown summary, file URLs, embedded suitability map,
        AUC, and variable importance.
    """
    vars_r = ", ".join(f'"{v.strip()}"' for v in bioclim_vars.split(","))
    ftypes_r = ", ".join(f'"{t.strip()}"' for t in feature_types.split(","))

    code = f'''
suppressPackageStartupMessages({{
  library(terra)
  library(sf)
  library(maxentcpp)
  {"library(arrow)" if not use_gbif_api else "library(rgbif)"}
}})

source("/workspace/scripts/maxent_pipeline.R")

# Override parse_args for programmatic invocation
opts <- list(
  species       = "{species}",
  bioclim_dir   = Sys.getenv("BIOCLIM_DIR", "/media/reumanlab/TOSHIBA_EXT/era5-bioclim"),
  ecoregions    = Sys.getenv("ECOREGIONS_DIR", "/home/a474r867/work/ecoregions"),
  gbif_parquet  = Sys.getenv("GBIF_PARQUET", "/media/reumanlab/TOSHIBA_EXT/gbifdata/occurrence/2026-06-01/occurrence.parquet"),
  output_dir    = "/workspace/jobs/maxent_{species.replace(" ", "_")}",
  bioclim_vars  = c({vars_r}),
  bioclim_year  = {bioclim_year}L,
  n_background  = {n_background}L,
  feature_types = c({ftypes_r}),
  n_hinges      = {n_hinges}L,
  max_iter      = {max_iter}L,
  iqr_factor    = {iqr_factor},
  ecoregion_pct = {ecoregion_pct},
  use_gbif_api  = {"TRUE" if use_gbif_api else "FALSE"},
  gbif_limit    = 50000L,
  seed          = {seed}L
)

tryCatch({{
  occ <- get_occurrences(opts$species, opts$gbif_parquet,
                         opts$use_gbif_api, opts$gbif_limit)
  occ <- filter_unique(occ)
  occ <- remove_outliers_iqr(occ, opts$iqr_factor)
  result <- extract_bioclim(occ, opts$bioclim_dir, opts$bioclim_vars, opts$bioclim_year)
  occ_env <- deduplicate_coords(result$occ)

  maxent_result <- fit_maxent_model(
    occ_env, result$stack, result$vars, opts$output_dir,
    opts$species, opts$n_background, opts$feature_types,
    opts$n_hinges, opts$max_iter, opts$seed
  )

  m_mask <- build_m_mask(occ, opts$ecoregions, opts$ecoregion_pct)
  env_masked <- crop_bioclim_with_mask(result$stack, m_mask)

  sp_clean <- gsub("[^a-zA-Z0-9]", "_", opts$species)
  out_path <- file.path(opts$output_dir, paste0(sp_clean, "_suitability.tif"))
  pred_raster <- project_maxent(maxent_result, env_masked, result$vars, out_path)
  paths <- write_outputs(pred_raster, maxent_result, occ_env,
                         opts$species, opts$output_dir)

  cat("\\n[RESULT_JSON]", jsonlite::toJSON(list(
    success = TRUE,
    species = opts$species,
    algorithm = "maxentcpp",
    n_points = nrow(occ_env),
    n_background = opts$n_background,
    variables = result$vars,
    auc = maxent_result$evaluation$auc,
    training_gain = maxent_result$fit_result$loss,
    output_dir = opts$output_dir,
    files = paths
  ), auto_unbox = TRUE), "\\n")
}}, error = function(e) {{
  cat("\\n[RESULT_JSON]", jsonlite::toJSON(list(
    success = FALSE,
    species = opts$species,
    algorithm = "maxentcpp",
    error = conditionMessage(e)
  ), auto_unbox = TRUE), "\\n")
}})
'''

    raw = execute_r_code(code=code, timeout=_R_EXEC_TIMEOUT, task_id=task_id)
    return _postprocess_model_result(raw, "MaxEnt (maxentcpp)")
