#!/bin/bash

input_image=${1:-/dss/dsshome1/0D/ge24tav3/checkpoints/custom_images/police-107.jpg}

export CUDA_VISIBLE_DEVICES=0
python scene_graph_gen.py \
  --config GroundingDINO/groundingdino/config/GroundingDINO_SwinT_OGC.py \
  --grounded_checkpoint weights/groundingdino_swint_ogc.pth \
  --sam_checkpoint weights/sam_vit_h_4b8939.pth \
  --input_image "$input_image" \
  --output_dir "outputs" \
  --box_threshold 0.15 \
  --text_threshold 0.1 \
  --iou_threshold 0.25  \
  --device "cuda"
