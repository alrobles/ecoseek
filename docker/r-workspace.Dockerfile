# R Workspace — rocker/geospatial + HTTP bridge for EcoSeek
#
# Provides a full R geospatial environment that Emily can execute code in
# via a lightweight HTTP API. Based on rocker/geospatial which includes:
#   sf, terra, raster, rgdal, stars, tmap, leaflet, mapview, etc.
#
# Extra ecology packages installed on top:
#   dismo, vegan, ape, picante, phytools, ENMeval, spocc, rgbif, taxize
#
# Build:
#   docker build -f docker/r-workspace.Dockerfile -t ecoseek-r-workspace .
#
# The HTTP bridge (Python) listens on port 8787 and accepts:
#   POST /execute  — run R code, return stdout/stderr/output files
#   GET  /health   — health check
#   GET  /packages — list installed R packages

FROM rocker/geospatial:latest

LABEL maintainer="EcoSeek <alrobles@ku.edu>"
LABEL description="R geospatial workspace with HTTP bridge for EcoSeek agentic loop"

# Install ecology/biodiversity R packages not in base rocker/geospatial
RUN install2.r --error --skipinstalled --ncpus -1 \
    dismo \
    vegan \
    ape \
    picante \
    phytools \
    ENMeval \
    spocc \
    rgbif \
    taxize \
    rnaturalearth \
    rnaturalearthdata \
    geodata \
    sdm \
    biomod2 \
    CoordinateCleaner \
    && rm -rf /tmp/downloaded_packages/

# Python for the HTTP bridge (already in rocker via reticulate, but ensure)
RUN apt-get update && apt-get install -y --no-install-recommends python3 && \
    rm -rf /var/lib/apt/lists/*

# Create workspace and R user library
RUN mkdir -p /workspace/jobs /workspace/R_libs /workspace/data

ENV R_WORKSPACE_DIR="/workspace"
ENV R_WORKSPACE_PORT="8787"
ENV R_EXEC_TIMEOUT="300"
ENV R_LIBS_USER="/workspace/R_libs"

# Copy the HTTP bridge server
COPY r-workspace/server.py /opt/r-workspace/server.py

EXPOSE 8787

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start_period=10s \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8787/health')" || exit 1

CMD ["python3", "/opt/r-workspace/server.py"]
