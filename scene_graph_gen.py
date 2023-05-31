'''
python scene_graph_gen.py --config GroundingDINO/groundingdino/config/GroundingDINO_SwinT_OGC.py  --grounded_checkpoint groundingdino_swint_ogc.pth --sam_checkpoint sam_vit_h_4b8939.pth --input_image assets/demo4.jpg --output_dir "outputs" --box_threshold 0.25 --text_threshold 0.2 --iou_threshold 0.5  --device "cpu"


'''


import argparse
import os
import copy

import numpy as np
import json
import torch
import torchvision
from PIL import Image, ImageDraw, ImageFont

# Grounding DINO
import groundingdino.datasets.transforms as T
from groundingdino.models import build_model
from groundingdino.util import box_ops
from groundingdino.util.slconfig import SLConfig
from groundingdino.util.utils import clean_state_dict, get_phrases_from_posmap

# segment anything
from segment_anything import build_sam, SamPredictor
import cv2
import numpy as np
import matplotlib.pyplot as plt

# BLIP
# from transformers import BlipProcessor, BlipForConditionalGeneration
from lavis.models import load_model_and_preprocess

# ChatGPT
# import openai
import sng_parser
import pickle
import json

def load_image(image_path):
    # load image
    image_pil = Image.open(image_path).convert("RGB")  # load image

    transform = T.Compose(
        [
            T.RandomResize([800], max_size=1333),
            T.ToTensor(),
            T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ]
    )
    image, _ = transform(image_pil, None)  # 3, h, w
    return image_pil, image


def generate_caption(raw_image,device):
    # unconditional image captioning
    # if device == "cuda":
    #     inputs = processor(raw_image, return_tensors="pt").to("cuda", torch.float16)
    # else:
    #     inputs = processor(raw_image, return_tensors="pt")
    inputs = processor["eval"](raw_image).unsqueeze(0).to(device)
    caption = blip_model.generate({"image": inputs})[0]
    return caption

def generate_tags(caption, split=','):
    graph = sng_parser.parse(caption)
    sng_parser.tprint(graph)
    obj_name = [i["head"] for i in graph['entities']]
    print(obj_name)
    tag = ""
    for i in obj_name:
        tag = tag + i +split
    return tag, graph

def graph_to_json(output_dir,graph):
    graph_json = {"class": "GraphLinksModel", "nodeDataArray": [], "linkDataArray": []}
    objs_name = [i["head"] for i in graph['entities']]
    for obj in objs_name:
        graph_json["nodeDataArray"].append({"key":obj,"color":"#ec8c69"})
    for rel in [i["relation"] for i in graph['relations']]:
        graph_json["nodeDataArray"].append({"key":rel, "color":"yellow"})

    for relation in graph['relations']:
        graph_json["linkDataArray"].append({"from":objs_name[relation["subject"]], "to":relation["relation"]})
        graph_json["linkDataArray"].append({"from":relation["relation"], "to":objs_name[relation["object"]]})
    with open(os.path.join(output_dir, "scenegraph.json"), "w") as file:
        json.dump(graph_json, file, separators=(',',':'))



# def generate_tags(caption, split=',', max_tokens=100, model="gpt-3.5-turbo"):
#     prompt = [
#         {
#             'role': 'system',
#             'content': 'Extract the unique nouns in the caption. Remove all the adjectives. ' + \
#                        f'List the nouns in singular form. Split them by "{split} ". ' + \
#                        f'Caption: {caption}.'
#         }
#     ]
#     response = openai.ChatCompletion.create(model=model, messages=prompt, temperature=0.6, max_tokens=max_tokens)
#     reply = response['choices'][0]['message']['content']
#     # sometimes return with "noun: xxx, xxx, xxx"
#     tags = reply.split(':')[-1].strip()
#     return tags
#
#
# def check_caption(caption, pred_phrases, max_tokens=100, model="gpt-3.5-turbo"):
#     object_list = [obj.split('(')[0] for obj in pred_phrases]
#     object_num = []
#     for obj in set(object_list):
#         object_num.append(f'{object_list.count(obj)} {obj}')
#     object_num = ', '.join(object_num)
#     print(f"Correct object number: {object_num}")
#
#     prompt = [
#         {
#             'role': 'system',
#             'content': 'Revise the number in the caption if it is wrong. ' + \
#                        f'Caption: {caption}. ' + \
#                        f'True object number: {object_num}. ' + \
#                        'Only give the revised caption: '
#         }
#     ]
#     response = openai.ChatCompletion.create(model=model, messages=prompt, temperature=0.6, max_tokens=max_tokens)
#     reply = response['choices'][0]['message']['content']
#     # sometimes return with "Caption: xxx, xxx, xxx"
#     caption = reply.split(':')[-1].strip()
#     return caption


def load_model(model_config_path, model_checkpoint_path, device):
    args = SLConfig.fromfile(model_config_path)
    args.device = device
    model = build_model(args)
    checkpoint = torch.load(model_checkpoint_path, map_location="cpu")
    load_res = model.load_state_dict(clean_state_dict(checkpoint["model"]), strict=False)
    print(load_res)
    _ = model.eval()
    return model


def get_grounding_output(model, image, caption, box_threshold, text_threshold, device="cpu"):
    caption = caption.lower()
    caption = caption.strip()
    if not caption.endswith("."):
        caption = caption + "."
    model = model.to(device)
    image = image.to(device)
    with torch.no_grad():
        outputs = model(image[None], captions=[caption])
    logits = outputs["pred_logits"].cpu().sigmoid()[0]  # (nq, 256)
    boxes = outputs["pred_boxes"].cpu()[0]  # (nq, 4)
    logits.shape[0]

    # filter output
    logits_filt = logits.clone()
    boxes_filt = boxes.clone()
    filt_mask = logits_filt.max(dim=1)[0] > box_threshold
    logits_filt = logits_filt[filt_mask]  # num_filt, 256
    boxes_filt = boxes_filt[filt_mask]  # num_filt, 4
    logits_filt.shape[0]

    # get phrase
    tokenlizer = model.tokenizer
    tokenized = tokenlizer(caption)
    # build pred
    pred_phrases = []
    scores = []
    for logit, box in zip(logits_filt, boxes_filt):
        pred_phrase = get_phrases_from_posmap(logit > text_threshold, tokenized, tokenlizer)
        pred_phrases.append(pred_phrase + f"({str(logit.max().item())[:4]})")
        scores.append(logit.max().item())

    return boxes_filt, torch.Tensor(scores), pred_phrases


def show_mask(mask, ax, random_color=False):
    if random_color:
        color = np.concatenate([np.random.random(3), np.array([0.6])], axis=0)
    else:
        color = np.array([30 / 255, 144 / 255, 255 / 255, 0.6])
    h, w = mask.shape[-2:]
    mask_image = mask.reshape(h, w, 1) * color.reshape(1, 1, -1)
    ax.imshow(mask_image)


def show_box(box, ax, label):
    x0, y0 = box[0], box[1]
    w, h = box[2] - box[0], box[3] - box[1]
    ax.add_patch(plt.Rectangle((x0, y0), w, h, edgecolor='green', facecolor=(0, 0, 0, 0), lw=2))
    ax.text(x0, y0, label)




def save_mask_data(output_dir, caption, mask_list, box_list, label_list):
    value = 0  # 0 for background

    mask_img = torch.zeros(mask_list.shape[-2:])
    for idx, mask in enumerate(mask_list):
        mask_img[mask.cpu().numpy()[0] == True] = value + idx + 1
    plt.figure(figsize=(10, 10))
    plt.imshow(mask_img.numpy())
    plt.axis('off')
    plt.savefig(os.path.join(output_dir, 'mask.jpg'), bbox_inches="tight", dpi=300, pad_inches=0.0)

    json_data = {
        'caption': caption,
        'mask': [{
            'value': value,
            'label': 'background'
        }]
    }
    for label, box in zip(label_list, box_list):
        value += 1
        name, logit = label.split('(')
        logit = logit[:-1]  # the last is ')'
        json_data['mask'].append({
            'value': value,
            'label': name,
            'logit': float(logit),
            'box': box.numpy().tolist(),
        })
    with open(os.path.join(output_dir, 'label.json'), 'w') as f:
        json.dump(json_data, f)


if __name__ == "__main__":

    parser = argparse.ArgumentParser("Grounded-Segment-Anything Demo", add_help=True)
    parser.add_argument("--config", type=str, required=True, help="path to config file")
    parser.add_argument(
        "--grounded_checkpoint", type=str, required=True, help="path to checkpoint file"
    )
    parser.add_argument(
        "--sam_checkpoint", type=str, required=True, help="path to checkpoint file"
    )
    parser.add_argument("--input_image", type=str, required=True, help="path to image file")
    parser.add_argument("--split", default=",", type=str, help="split for text prompt")
    # parser.add_argument("--openai_key", type=str, required=True, help="key for chatgpt")
    # parser.add_argument("--openai_proxy", default=None, type=str, help="proxy for chatgpt")
    parser.add_argument(
        "--output_dir", "-o", type=str, default="outputs", required=True, help="output directory"
    )

    parser.add_argument("--box_threshold", type=float, default=0.25, help="box threshold")
    parser.add_argument("--text_threshold", type=float, default=0.2, help="text threshold")
    parser.add_argument("--iou_threshold", type=float, default=0.5, help="iou threshold")

    parser.add_argument("--device", type=str, default="cpu", help="running on cpu only!, default=False")
    args = parser.parse_args()

    # cfg
    config_file = args.config  # change the path of the model config file
    grounded_checkpoint = args.grounded_checkpoint  # change the path of the model
    sam_checkpoint = args.sam_checkpoint
    image_path = args.input_image
    split = args.split
    # openai_key = args.openai_key
    # openai_proxy = args.openai_proxy
    output_dir = args.output_dir
    box_threshold = args.box_threshold
    text_threshold = args.text_threshold
    iou_threshold = args.iou_threshold
    device = args.device

    # openai.api_key = openai_key
    # if openai_proxy:
    #     openai.proxy = {"http": openai_proxy, "https": openai_proxy}

    # make dir
    os.makedirs(output_dir, exist_ok=True)
    # load image
    image_pil, image = load_image(image_path)
    # load model
    model = load_model(config_file, grounded_checkpoint, device=device)

    # visualize raw image
    image_pil.save(os.path.join(output_dir, "raw_image.jpg"))

    # generate caption and tags
    # use Tag2Text can generate better captions
    # https://huggingface.co/spaces/xinyu1205/Tag2Text
    # but there are some bugs...
    # processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-large")
    if device == "cuda":
        # blip_model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-large",
        #                                                           torch_dtype=torch.float16).to("cuda")
        blip_device=torch.device("cuda")
    else:
        # blip_model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-large")
        blip_device = torch.device("cpu")
    blip_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    blip_model, processor, _ = load_model_and_preprocess(
        name="blip_caption", model_type="base_coco", is_eval=True, device=blip_device
    )
    caption = generate_caption(image_pil, device=blip_device)
    print(f"Caption: {caption}")
    # Currently ", " is better for detecting single tags
    # while ". " is a little worse in some case
    text_prompt, scene_graph = generate_tags(caption, split=split)
    print(f"Tags: {text_prompt}")

    # run grounding dino model
    boxes_filt, scores, pred_phrases = get_grounding_output(
        model, image, text_prompt, box_threshold, text_threshold, device=device
    )

    # initialize SAM
    predictor = SamPredictor(build_sam(checkpoint=sam_checkpoint).to(device))
    image = cv2.imread(image_path)
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    predictor.set_image(image)

    size = image_pil.size
    H, W = size[1], size[0]
    for i in range(boxes_filt.size(0)):
        boxes_filt[i] = boxes_filt[i] * torch.Tensor([W, H, W, H])
        boxes_filt[i][:2] -= boxes_filt[i][2:] / 2
        boxes_filt[i][2:] += boxes_filt[i][:2]

    boxes_filt = boxes_filt.cpu()
    # use NMS to handle overlapped boxes
    print(f"Before NMS: {boxes_filt.shape[0]} boxes")
    nms_idx = torchvision.ops.nms(boxes_filt, scores, iou_threshold).numpy().tolist()
    boxes_filt = boxes_filt[nms_idx]
    pred_phrases = [pred_phrases[idx] for idx in nms_idx]
    print(f"After NMS: {boxes_filt.shape[0]} boxes")
    # caption = check_caption(caption, pred_phrases)
    # print(f"Revise caption with number: {caption}")

    transformed_boxes = predictor.transform.apply_boxes_torch(boxes_filt, image.shape[:2]).to(device)

    masks, _, _ = predictor.predict_torch(
        point_coords=None,
        point_labels=None,
        boxes=transformed_boxes.to(device),
        multimask_output=False,
    )

    # draw output image
    plt.figure(figsize=(10, 10))
    plt.imshow(image)
    for mask in masks:
        show_mask(mask.cpu().numpy(), plt.gca(), random_color=True)
    for box, label in zip(boxes_filt, pred_phrases):
        show_box(box.numpy(), plt.gca(), label)

    plt.title(caption)
    plt.axis('off')
    plt.savefig(
        os.path.join(output_dir, "automatic_label_output.jpg"),
        bbox_inches="tight", dpi=300, pad_inches=0.0
    )
    graph_to_json(output_dir, scene_graph)
    save_mask_data(output_dir, caption, masks, boxes_filt, pred_phrases)
