import os
import sys

import math

import torch


def _require_executorch() -> None:
	try:
		import executorch  # noqa: F401
	except Exception as exc:
		raise RuntimeError(
			"ExecuTorch is not available. Install executorch to run this test."
		) from exc


def _require_pillow() -> None:
	try:
		import PIL  # noqa: F401
	except Exception as exc:
		raise RuntimeError("Pillow is required for image testing.") from exc


def load_class_names(metadata_path: str) -> list[str]:
	if not os.path.exists(metadata_path):
		return []

	try:
		import yaml  # type: ignore
	except Exception:
		yaml = None

	if yaml is not None:
		with open(metadata_path, "r", encoding="utf-8") as f:
			data = yaml.safe_load(f)
		names = data.get("names", {}) if isinstance(data, dict) else {}
		if isinstance(names, dict):
			return [names[k] for k in sorted(names.keys())]
		if isinstance(names, list):
			return names
		return []

	names = {}
	in_names = False
	with open(metadata_path, "r", encoding="utf-8") as f:
		for line in f:
			line = line.rstrip("\n")
			if line.startswith("names:"):
				in_names = True
				continue
			if in_names:
				if not line.startswith("  "):
					break
				parts = line.strip().split(":", 1)
				if len(parts) == 2:
					idx = parts[0].strip()
					name = parts[1].strip()
					try:
						names[int(idx)] = name
					except ValueError:
						pass

	return [names[k] for k in sorted(names.keys())]


def run_pte(pte_path: str, example: torch.Tensor) -> torch.Tensor:
	_require_executorch()

	from executorch.runtime import Runtime

	runtime = Runtime.get()
	program = runtime.load_program(pte_path)
	method = program.load_method("forward")
	outputs = method.execute([example]) # type: ignore
	if isinstance(outputs, (list, tuple)) and outputs:
		return outputs[0]
	return outputs # type: ignore


def letterbox(image, new_shape=640, color=(114, 114, 114)):
	from PIL import Image

	if isinstance(new_shape, int):
		new_shape = (new_shape, new_shape)

	width, height = image.size
	ratio = min(new_shape[0] / height, new_shape[1] / width)
	new_unpad = (int(round(width * ratio)), int(round(height * ratio)))
	resize_image = image.resize(new_unpad, resample=Image.BILINEAR) # type: ignore

	pad_w = new_shape[1] - new_unpad[0]
	pad_h = new_shape[0] - new_unpad[1]
	pad_left = pad_w // 2
	pad_top = pad_h // 2

	new_image = Image.new("RGB", (new_shape[1], new_shape[0]), color)
	new_image.paste(resize_image, (pad_left, pad_top))

	return new_image, ratio, (pad_left, pad_top)


def preprocess_image(image_path: str, img_size: int = 640) -> tuple[torch.Tensor, tuple[int, int], float, tuple[int, int]]:
	_require_pillow()

	from PIL import Image

	image = Image.open(image_path).convert("RGB")
	orig_size = image.size
	resized, ratio, pad = letterbox(image, new_shape=img_size)
	image_tensor = torch.from_numpy(
		torch.ByteTensor(torch.ByteStorage.from_buffer(resized.tobytes())).numpy()
	).reshape(img_size, img_size, 3)
	image_tensor = image_tensor.permute(2, 0, 1).contiguous().float() / 255.0
	image_tensor = image_tensor.unsqueeze(0)
	return image_tensor, orig_size, ratio, pad


def xywh_to_xyxy(boxes: torch.Tensor) -> torch.Tensor:
	x, y, w, h = boxes.unbind(-1)
	x1 = x - w / 2
	y1 = y - h / 2
	x2 = x + w / 2
	y2 = y + h / 2
	return torch.stack((x1, y1, x2, y2), dim=-1)


def nms(boxes: torch.Tensor, scores: torch.Tensor, iou_thres: float) -> torch.Tensor:
	if boxes.numel() == 0:
		return torch.empty((0,), dtype=torch.long)

	indices = scores.argsort(descending=True)
	keep = []
	while indices.numel() > 0:
		i = indices[0]
		keep.append(i)
		if indices.numel() == 1:
			break
		current = boxes[i].unsqueeze(0)
		others = boxes[indices[1:]]
		x1 = torch.maximum(current[:, 0], others[:, 0])
		y1 = torch.maximum(current[:, 1], others[:, 1])
		x2 = torch.minimum(current[:, 2], others[:, 2])
		y2 = torch.minimum(current[:, 3], others[:, 3])
		inter_w = (x2 - x1).clamp(min=0)
		inter_h = (y2 - y1).clamp(min=0)
		inter = inter_w * inter_h
		area_current = (current[:, 2] - current[:, 0]).clamp(min=0) * (
			current[:, 3] - current[:, 1]
		).clamp(min=0)
		area_others = (others[:, 2] - others[:, 0]).clamp(min=0) * (
			others[:, 3] - others[:, 1]
		).clamp(min=0)
		union = area_current + area_others - inter + 1e-6
		iou = inter / union
		indices = indices[1:][iou <= iou_thres]

	return torch.stack(keep) if keep else torch.empty((0,), dtype=torch.long)


def postprocess(
	output: torch.Tensor,
	orig_size: tuple[int, int],
	ratio: float,
	pad: tuple[int, int],
	class_names: list[str] | None = None,
	conf_thres: float = 0.25,
	iou_thres: float = 0.45,
):
	if output.dim() == 3:
		boxes = output.squeeze(0).transpose(0, 1)
	else:
		boxes = output

	class_count = len(class_names) if class_names else max(0, boxes.shape[1] - 4)
	channel_count = boxes.shape[1]
	box_xywh = boxes[:, :4]

	if channel_count == 4 + class_count:
		class_scores = boxes[:, 4:]
		conf, cls = class_scores.max(dim=1)
	elif channel_count == 5 + class_count:
		obj = boxes[:, 4]
		class_scores = boxes[:, 5:]
		conf, cls = class_scores.max(dim=1)
		conf = conf * obj
	else:
		class_scores = boxes[:, 4:]
		conf, cls = class_scores.max(dim=1)

	mask = conf >= conf_thres
	if mask.sum() == 0:
		return torch.empty((0, 4)), torch.empty((0,)), torch.empty((0,), dtype=torch.long)

	box_xyxy = xywh_to_xyxy(box_xywh[mask])
	conf = conf[mask]
	cls = cls[mask]

	keep = nms(box_xyxy, conf, iou_thres)
	box_xyxy = box_xyxy[keep]
	conf = conf[keep]
	cls = cls[keep]

	pad_left, pad_top = pad
	box_xyxy[:, 0] = (box_xyxy[:, 0] - pad_left) / ratio
	box_xyxy[:, 1] = (box_xyxy[:, 1] - pad_top) / ratio
	box_xyxy[:, 2] = (box_xyxy[:, 2] - pad_left) / ratio
	box_xyxy[:, 3] = (box_xyxy[:, 3] - pad_top) / ratio

	width, height = orig_size
	box_xyxy[:, 0].clamp_(0, width)
	box_xyxy[:, 2].clamp_(0, width)
	box_xyxy[:, 1].clamp_(0, height)
	box_xyxy[:, 3].clamp_(0, height)

	return box_xyxy, conf, cls


def draw_boxes(image_path: str, boxes, scores, classes, output_path: str, class_names: list[str]) -> None:
	_require_pillow()

	from PIL import Image, ImageDraw, ImageFont

	image = Image.open(image_path).convert("RGB")
	draw = ImageDraw.Draw(image)
	font = None
	try:
		font = ImageFont.load_default()
	except Exception:
		font = None

	for box, score, cls_idx in zip(boxes, scores, classes):
		x1, y1, x2, y2 = [float(v) for v in box.tolist()]
		cls_id = int(cls_idx)
		name = class_names[cls_id] if 0 <= cls_id < len(class_names) else str(cls_id)
		label = f"{name} {score:.2f}"
		draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=2)
		text_w = draw.textlength(label, font=font) if font else 0
		text_h = 10
		text_bg = [x1, max(0, y1 - text_h - 2), x1 + text_w + 4, y1]
		draw.rectangle(text_bg, fill=(255, 0, 0))
		draw.text((x1 + 2, max(0, y1 - text_h - 1)), label, fill=(255, 255, 255), font=font)

	image.save(output_path)


def main() -> int:
	pte_path = os.path.join(
		os.path.dirname(__file__),
		"yolo26n_executorch_model",
		"yolo26n.pte",
	)
	metadata_path = os.path.join(
		os.path.dirname(__file__),
		"yolo26n_executorch_model",
		"metadata.yaml",
	)

	if not os.path.exists(pte_path):
		print(f"Missing model file: {pte_path}")
		return 1

	image_path = os.path.join(os.path.dirname(__file__), "bus.jpg")
	if not os.path.exists(image_path):
		print(f"Missing image file: {image_path}")
		return 1

	class_names = load_class_names(metadata_path)
	if not class_names:
		print("Warning: metadata.yaml missing class names, falling back to indices.")

	example, orig_size, ratio, pad = preprocess_image(image_path, img_size=640)
	et_out = run_pte(pte_path, example)

	if not isinstance(et_out, torch.Tensor):
		print("Unexpected output type:", type(et_out))
		return 1

	print("ExecuTorch output shape:", tuple(et_out.shape))
	boxes, scores, classes = postprocess(
		et_out,
		orig_size,
		ratio,
		pad,
		class_names=class_names,
	)
	print("Detections:", int(boxes.shape[0]))

	output_path = os.path.join(os.path.dirname(__file__), "bus_annotated.jpg")
	draw_boxes(image_path, boxes, scores, classes, output_path, class_names)
	print(f"Annotated image saved to: {output_path}")

	print("ExecuTorch image test passed.")
	return 0


if __name__ == "__main__":
	sys.exit(main())