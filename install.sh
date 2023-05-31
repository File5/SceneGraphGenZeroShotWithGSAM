#!/bin/bash

# in a conda activated environment

conda install pytorch==1.13.1 torchvision==0.14.1 torchaudio==0.13.1 pytorch-cuda=11.7 -c pytorch -c nvidia

# segment-anything
git clone git+https://github.com/facebookresearch/segment-anything.git segment_anything_latest
(cd segment_anything_latest && pip install -e .)
# + deps
pip install opencv-python pycocotools matplotlib onnxruntime onnx

# GroundingDINO
git clone https://github.com/IDEA-Research/GroundingDINO.git GroundingDINO_latest
(cd GroundingDINO_latest && pip install -e .)
mkdir GroundingDINO_latest/weights
curl -o GroundingDINO_latest/weights/groundingdino_swint_ogc.pth https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth

mkdir weights
(cd weights && wget https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth && wget https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth)

# LAVIS
git clone https://github.com/salesforce/LAVIS.git
cd LAVIS
pip install -e .

# install diffusers
pip install --upgrade diffusers[torch]

# sng_parser
pip install SceneGraphParser
python -m spacy download en  # to use the parser for English

# fixes
pip install transformers==4.25

