FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates ghostscript python3 python3-numpy python3-pil python3-scipy \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
COPY read_arpt_dgm_png.py tag.py cycle.py ReadArptDgmPng_learnt.csv ./

ENV OUT=/out
CMD ["python3", "tag.py"]
